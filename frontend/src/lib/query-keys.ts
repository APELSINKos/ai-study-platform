/**
 * Every query key in the app. A key belongs either to `useQuery` or to `useInfiniteQuery`, never
 * to both, because the two cache differently shaped data under it. Keys nest, so a prefix reaches
 * everything below it: mutations invalidate `workspaces`, and deletes also remove the deleted
 * item's detail key, which takes its document list or chunks with it.
 */
export const queryKeys = {
  workspaces: ["workspaces"] as const,
  /** Infinite, `WORKSPACE_LIST_PAGE_SIZE` per page. */
  workspaceList: ["workspaces", "list"] as const,
  /** A plain query for the dashboard: the `RECENT_WORKSPACES_COUNT` latest workspaces. */
  recentWorkspaces: ["workspaces", "recent"] as const,
  workspace: (id: string) => ["workspaces", "detail", id] as const,
  /** Infinite, `WORKSPACE_DOCUMENTS_PAGE_SIZE` per page. */
  workspaceDocuments: (id: string) => ["workspaces", "detail", id, "documents"] as const,
  document: (id: string) => ["documents", id] as const,
  /** Infinite. */
  documentChunks: (id: string) => ["documents", id, "chunks"] as const,
  meta: ["meta"] as const,
};

export const WORKSPACE_LIST_PAGE_SIZE = 20;
export const RECENT_WORKSPACES_COUNT = 3;
export const WORKSPACE_DOCUMENTS_PAGE_SIZE = 50;
