import { apiFetch } from "@/lib/api/client";
import type { WorkspaceCreateRequest, WorkspaceOut, WorkspacePage } from "@/lib/api/types";

/** One page of the user's workspaces, the most recently updated first. */
export function fetchWorkspacePage(page: number, pageSize: number): Promise<WorkspacePage> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return apiFetch<WorkspacePage>(`/workspaces?${query.toString()}`);
}

export function createWorkspace(payload: WorkspaceCreateRequest): Promise<WorkspaceOut> {
  return apiFetch<WorkspaceOut>("/workspaces", { method: "POST", json: payload });
}
