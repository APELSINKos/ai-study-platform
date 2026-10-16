import { apiFetch } from "@/lib/api/client";
import type { DocumentOut, DocumentPage } from "@/lib/api/types";

function documentPath(id: string): string {
  return `/documents/${encodeURIComponent(id)}`;
}

function workspaceDocumentsPath(workspaceId: string): string {
  return `/workspaces/${encodeURIComponent(workspaceId)}/documents`;
}

/** One page of a workspace's documents, the newest first. */
export function fetchDocumentPage(
  workspaceId: string,
  page: number,
  pageSize: number,
): Promise<DocumentPage> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return apiFetch<DocumentPage>(`${workspaceDocumentsPath(workspaceId)}?${query.toString()}`);
}

/** Sends one file to a workspace; the new document comes back queued for processing. */
export function uploadDocument(workspaceId: string, file: File): Promise<DocumentOut> {
  const body = new FormData();
  body.append("file", file);
  return apiFetch<DocumentOut>(workspaceDocumentsPath(workspaceId), { method: "POST", body });
}

/** Queues a failed or stalled document for processing again; answers with its new state. */
export function retryDocument(id: string): Promise<DocumentOut> {
  return apiFetch<DocumentOut>(`${documentPath(id)}/retry`, { method: "POST" });
}

/** Deletes the document with its fragments and its file. */
export function deleteDocument(id: string): Promise<void> {
  return apiFetch<void>(documentPath(id), { method: "DELETE" });
}
