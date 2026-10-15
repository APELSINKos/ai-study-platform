import { apiFetch } from "@/lib/api/client";
import type { WorkspacePage } from "@/lib/api/types";

/** One page of the user's workspaces, the most recently updated first. */
export function fetchWorkspacePage(page: number, pageSize: number): Promise<WorkspacePage> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return apiFetch<WorkspacePage>(`/workspaces?${query.toString()}`);
}
