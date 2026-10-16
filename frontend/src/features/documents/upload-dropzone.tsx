"use client";

import { UploadSimpleIcon } from "@phosphor-icons/react";
import { useLocale, useTranslations } from "next-intl";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent as ReactDragEvent,
} from "react";

import { Button } from "@/components/ui/button";
import { useMeta } from "@/features/meta/hooks";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

import { documentErrorMessage } from "./error-message";
import { acceptAttribute, listExtensions } from "./file-rules";
import { UploadResults } from "./upload-results";
import { useUploadQueue } from "./use-upload-queue";

function carriesFiles(dataTransfer: DataTransfer | null): boolean {
  return dataTransfer !== null && Array.from(dataTransfer.types).includes("Files");
}

interface UploadDropzoneProps {
  workspaceId: string;
  className?: string;
}

/**
 * Where files join the workspace: Upload files opens the file picker, and files can be dropped
 * on the zone as well. Files are checked against the limits from GET /meta before they are
 * sent, then uploaded one at a time; the results are listed under the zone.
 */
export function UploadDropzone({ workspaceId, className }: UploadDropzoneProps) {
  const t = useTranslations("Documents.upload");
  const tErrors = useTranslations("Documents.errors");
  const locale = useLocale();
  const meta = useMeta();
  const queue = useUploadQueue(workspaceId);
  const rules = meta.data;
  const rulesId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  // Set by Try again, so that Upload files takes the focus once the limits arrive.
  const focusUploadRef = useRef(false);
  // Moving onto a child fires its dragenter before the zone's dragleave, so both are counted.
  const dragDepthRef = useRef(0);
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    // A file dropped beside the zone would open in the browser and take the user off the page.
    // The zone's own handlers run first, so an event it took is already marked as handled.
    function refuseFiles(event: DragEvent) {
      if (event.defaultPrevented || !carriesFiles(event.dataTransfer)) {
        return;
      }
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "none";
      }
    }
    window.addEventListener("dragover", refuseFiles);
    window.addEventListener("drop", refuseFiles);
    return () => {
      window.removeEventListener("dragover", refuseFiles);
      window.removeEventListener("drop", refuseFiles);
    };
  }, []);

  function takesDrag(event: ReactDragEvent<HTMLElement>): boolean {
    return rules !== undefined && carriesFiles(event.dataTransfer);
  }

  function addFiles(files: File[]) {
    if (rules !== undefined && files.length > 0) {
      queue.add(files, rules);
    }
  }

  function handleDragEnter(event: ReactDragEvent<HTMLDivElement>) {
    if (!takesDrag(event)) {
      return;
    }
    event.preventDefault();
    dragDepthRef.current += 1;
    setIsDragging(true);
  }

  function handleDragLeave(event: ReactDragEvent<HTMLDivElement>) {
    if (!takesDrag(event)) {
      return;
    }
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragging(false);
    }
  }

  function handleDragOver(event: ReactDragEvent<HTMLDivElement>) {
    if (!takesDrag(event)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleDrop(event: ReactDragEvent<HTMLDivElement>) {
    if (!takesDrag(event)) {
      return;
    }
    event.preventDefault();
    dragDepthRef.current = 0;
    setIsDragging(false);
    addFiles(Array.from(event.dataTransfer.files));
  }

  function handleChosenFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    // Emptied, so that choosing the same file again counts as a change.
    event.currentTarget.value = "";
    addFiles(files);
  }

  function attachUploadButton(button: HTMLButtonElement | null) {
    buttonRef.current = button;
    if (button && focusUploadRef.current) {
      focusUploadRef.current = false;
      button.focus();
    }
  }

  function loadLimitsAgain() {
    focusUploadRef.current = true;
    void meta.refetch();
  }

  function clearResults() {
    queue.clear();
    // Clear goes with the results, so the focus moves back to where files are added.
    buttonRef.current?.focus();
  }

  const isBusy = rules === undefined || queue.isUploading;

  return (
    <div className={className}>
      <div
        data-dragging={isDragging}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className={cn(
          "border-rule-strong rounded border border-dashed px-5 py-5 sm:px-6",
          isDragging && "border-pen bg-pen/5 border-solid",
        )}
      >
        {rules === undefined && meta.isError ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <p role="alert" className="text-ink-soft text-sm">
              {documentErrorMessage(meta.error, "loadLimits", tErrors)}
            </p>
            <Button
              variant="secondary"
              size="sm"
              isLoading={meta.isFetching}
              onClick={loadLimitsAgain}
            >
              {t("retry")}
            </Button>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Button
                ref={attachUploadButton}
                variant="primary"
                isLoading={isBusy}
                aria-describedby={rules === undefined ? undefined : rulesId}
                onClick={() => inputRef.current?.click()}
              >
                {isBusy ? null : <UploadSimpleIcon aria-hidden />}
                {t("button")}
              </Button>
              {rules === undefined ? null : (
                // Dragging needs a mouse or a trackpad, so touch screens are not told of it.
                <p
                  className={cn(
                    "text-sm pointer-coarse:hidden",
                    isDragging ? "text-ink font-medium" : "text-ink-soft",
                  )}
                >
                  {isDragging ? t("dropHint") : t("dragHint")}
                </p>
              )}
            </div>
            {rules === undefined ? null : (
              <>
                <p id={rulesId} className="text-ink-soft mt-3 text-sm">
                  {t("rules", {
                    types: listExtensions(rules, locale),
                    size: formatBytes(rules.max_upload_bytes, locale),
                  })}
                </p>
                <input
                  ref={inputRef}
                  type="file"
                  hidden
                  multiple
                  accept={acceptAttribute(rules)}
                  onChange={handleChosenFiles}
                />
              </>
            )}
          </>
        )}
      </div>
      <UploadResults items={queue.items} onClear={clearResults} />
    </div>
  );
}
