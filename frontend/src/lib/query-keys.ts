/**
 * The query keys of the workspaces, the documents and /meta; the signed-in user's key lives with
 * the auth hooks. A key belongs either to `useQuery` or to `useInfiniteQuery`, never to both,
 * because the two cache differently shaped data under it. Keys nest, and invalidating or removing
 * a prefix reaches every key below it: `workspaces` takes in the lists, each workspace and its
 * document list, but not a document's own page and fragments, which sit under `documents`.
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
  documents: ["documents"] as const,
  document: (id: string) => ["documents", id] as const,
  /** Infinite, `DOCUMENT_CHUNKS_PAGE_SIZE` per page. */
  documentChunks: (id: string) => ["documents", id, "chunks"] as const,
  meta: ["meta"] as const,
};

export const WORKSPACE_LIST_PAGE_SIZE = 20;
export const RECENT_WORKSPACES_COUNT = 3;
export const WORKSPACE_DOCUMENTS_PAGE_SIZE = 50;
export const DOCUMENT_CHUNKS_PAGE_SIZE = 50;
