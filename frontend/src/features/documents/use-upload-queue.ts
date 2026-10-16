import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { ApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/query-keys";

import { uploadDocument } from "./api";
import { checkFile, type FileRejection, type FileRules } from "./file-rules";

/** Refusals that the files still waiting would meet as well, so those are kept back. */
const THROTTLE_CODES: ReadonlySet<string> = new Set(["rate_limited", "too_many_active_documents"]);

export type UploadState =
  | { kind: "rejected"; reason: FileRejection; rules: FileRules }
  | { kind: "waiting" }
  | { kind: "uploading" }
  | { kind: "uploaded" }
  | { kind: "failed"; error: unknown }
  | { kind: "notSent"; retryAfterSeconds: number | null };

/** A file the user added, with what became of it. */
export interface UploadItem {
  id: number;
  name: string;
  size: number;
  state: UploadState;
}

interface QueuedFile {
  id: number;
  file: File;
  workspaceId: string;
}

function isThrottled(error: unknown): error is ApiError {
  return error instanceof ApiError && THROTTLE_CODES.has(error.code);
}

function isPending(item: UploadItem): boolean {
  return item.state.kind === "waiting" || item.state.kind === "uploading";
}

/**
 * Uploads files one at a time, in the order they were added. A file that breaks a rule from
 * GET /meta is listed as rejected and never sent. Files added during a run join its end; files
 * added after it start a new list.
 */
export function useUploadQueue(workspaceId: string) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<UploadItem[]>([]);
  // Touched only by the handlers that add files and by the run they start, never in render.
  const queueRef = useRef<QueuedFile[]>([]);
  const isRunningRef = useRef(false);
  const lastIdRef = useRef(0);

  function setState(ids: readonly number[], state: UploadState) {
    setItems((current) =>
      current.map((item) => (ids.includes(item.id) ? { ...item, state } : item)),
    );
  }

  async function run() {
    try {
      for (let next = queueRef.current.shift(); next; next = queueRef.current.shift()) {
        setState([next.id], { kind: "uploading" });
        try {
          await uploadDocument(next.workspaceId, next.file);
          setState([next.id], { kind: "uploaded" });
          // The new document then shows in the list, and the list asks for news until it is ready.
          void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
        } catch (error) {
          setState([next.id], { kind: "failed", error });
          if (isThrottled(error)) {
            const keptBack = queueRef.current.splice(0).map((queued) => queued.id);
            setState(keptBack, { kind: "notSent", retryAfterSeconds: error.retryAfterSeconds });
          }
        }
      }
    } finally {
      isRunningRef.current = false;
    }
  }

  function add(files: readonly File[], rules: FileRules) {
    const added = files.map((file): UploadItem => {
      lastIdRef.current += 1;
      const id = lastIdRef.current;
      const reason = checkFile(file, rules);
      if (reason !== null) {
        return { id, name: file.name, size: file.size, state: { kind: "rejected", reason, rules } };
      }
      queueRef.current.push({ id, file, workspaceId });
      return { id, name: file.name, size: file.size, state: { kind: "waiting" } };
    });
    const isRunning = isRunningRef.current;
    setItems((current) => (isRunning ? [...current, ...added] : added));
    if (!isRunning && queueRef.current.length > 0) {
      isRunningRef.current = true;
      void run();
    }
  }

  function clear() {
    setItems([]);
  }

  return { items, isUploading: items.some(isPending), add, clear };
}
