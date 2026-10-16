import { apiFetch } from "@/lib/api/client";
import type { DocumentOut, DocumentPage } from "@/lib/api/types";

function documentPath(id: string): string {
  return `/documents/${encodeURIComponent(id)}`;
}

/** One page of a workspace's documents, the newest first. */
export function fetchDocumentPage(
  workspaceId: string,
  page: number,
  pageSize: number,
): Promise<DocumentPage> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return apiFetch<DocumentPage>(
    `/workspaces/${encodeURIComponent(workspaceId)}/documents?${query.toString()}`,
  );
}

/** Queues a failed or stalled document for processing again; answers with its new state. */
export function retryDocument(id: string): Promise<DocumentOut> {
  return apiFetch<DocumentOut>(`${documentPath(id)}/retry`, { method: "POST" });
}

/** Deletes the document with its fragments and its file. */
export function deleteDocument(id: string): Promise<void> {
  return apiFetch<void>(documentPath(id), { method: "DELETE" });
}
