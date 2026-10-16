import { isClientError } from "@/lib/api/errors";
import type { DocumentErrorCode, DocumentOut, DocumentStatus } from "@/lib/api/types";

/** The stages a document passes on its way to ready, in order; failed branches off them. */
export const DOCUMENT_STAGES = [
  "uploaded",
  "processing",
  "indexing",
  "ready",
] as const satisfies readonly DocumentStatus[];

/** A status that is still on its way to ready or failed. */
export type ActiveStatus = Exclude<DocumentStatus, "ready" | "failed">;

/** How often a list asks again while a document is on its way. */
export const ACTIVE_POLL_INTERVAL_MS = 2000;
/** A stalled document changes only when someone retries it, so asking often is wasted. */
export const STALLED_POLL_INTERVAL_MS = 15000;

/** The code an automatic retry waits with, as uploaded, after the AI service did not answer. */
const RETRY_PENDING_CODE: DocumentErrorCode = "ai_unavailable";
/** The failed rows the database forbids without a code still need a sentence. */
const UNKNOWN_FAILURE_CODE: DocumentErrorCode = "internal_error";

export type DocumentProgress =
  | { kind: "ready" }
  | { kind: "failed"; errorCode: DocumentErrorCode }
  | { kind: "active"; stage: ActiveStatus; note: "stalled" | "retryPending" | null };

export interface DocumentTally {
  active: number;
  ready: number;
  failed: number;
}

export function isActive(document: Pick<DocumentOut, "status">): boolean {
  return document.status !== "ready" && document.status !== "failed";
}

/**
 * When to ask for the documents again: soon while one is on its way, rarely when all of those
 * have stalled, and never once they are all done or the API has refused the request.
 */
export function pollInterval(documents: readonly DocumentOut[], error: unknown): number | false {
  if (isClientError(error)) {
    return false;
  }
  const active = documents.filter(isActive);
  if (active.length === 0) {
    return false;
  }
  return active.every((document) => document.can_retry)
    ? STALLED_POLL_INTERVAL_MS
    : ACTIVE_POLL_INTERVAL_MS;
}

/** Where a document stands, as its row tells it. */
export function documentProgress(document: DocumentOut): DocumentProgress {
  switch (document.status) {
    case "ready":
      return { kind: "ready" };
    case "failed":
      return { kind: "failed", errorCode: document.error_code ?? UNKNOWN_FAILURE_CODE };
    default:
      return { kind: "active", stage: document.status, note: activeNote(document) };
  }
}

function activeNote(document: DocumentOut): "stalled" | "retryPending" | null {
  // A document that can be retried while on its way has not moved for too long.
  if (document.can_retry) {
    return "stalled";
  }
  if (document.status === "uploaded" && document.error_code === RETRY_PENDING_CODE) {
    return "retryPending";
  }
  return null;
}

export function tallyDocuments(documents: readonly DocumentOut[]): DocumentTally {
  const tally: DocumentTally = { active: 0, ready: 0, failed: 0 };
  for (const document of documents) {
    if (document.status === "ready") {
      tally.ready += 1;
    } else if (document.status === "failed") {
      tally.failed += 1;
    } else {
      tally.active += 1;
    }
  }
  return tally;
}
