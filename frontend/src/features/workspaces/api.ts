import { apiFetch } from "@/lib/api/client";
import type {
  WorkspaceCreateRequest,
  WorkspaceOut,
  WorkspacePage,
  WorkspaceUpdateRequest,
} from "@/lib/api/types";

/** The id may come from the address bar, so it is encoded to stay a single path segment. */
function workspacePath(id: string): string {
  return `/workspaces/${encodeURIComponent(id)}`;
}

/** One page of the user's workspaces, the most recently updated first. */
export function fetchWorkspacePage(page: number, pageSize: number): Promise<WorkspacePage> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return apiFetch<WorkspacePage>(`/workspaces?${query.toString()}`);
}

export function createWorkspace(payload: WorkspaceCreateRequest): Promise<WorkspaceOut> {
  return apiFetch<WorkspaceOut>("/workspaces", { method: "POST", json: payload });
}

export function fetchWorkspace(id: string): Promise<WorkspaceOut> {
  return apiFetch<WorkspaceOut>(workspacePath(id));
}

/** Changes only the fields sent; null removes the description or the exam date. */
export function updateWorkspace(
  id: string,
  changes: WorkspaceUpdateRequest,
): Promise<WorkspaceOut> {
  return apiFetch<WorkspaceOut>(workspacePath(id), { method: "PATCH", json: changes });
}

/** Deletes the workspace together with its documents and their files. */
export function deleteWorkspace(id: string): Promise<void> {
  return apiFetch<void>(workspacePath(id), { method: "DELETE" });
}
