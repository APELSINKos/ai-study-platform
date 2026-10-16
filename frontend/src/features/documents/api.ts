import { apiFetch } from "@/lib/api/client";
import type { DocumentPage } from "@/lib/api/types";

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
