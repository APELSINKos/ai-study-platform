/**
 * The query keys of the workspaces, the documents, the searches and /meta. Keys that only one
 * feature uses, such as the signed-in user's or the readiness check's, live with that feature's
 * hooks. A key belongs either to `useQuery` or to `useInfiniteQuery`, never to both, because the
 * two cache differently shaped data under it. Keys nest, and invalidating or removing a prefix
 * reaches every key below it: `workspaces` takes in the lists, each workspace and its document
 * list, but not a document's own page and fragments, which sit under `documents`, nor the
 * searches, which sit under `search` so that uploads and retries never run them again.
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
  /** Every search of one workspace. */
  workspaceSearches: (workspaceId: string) => ["search", workspaceId] as const,
  /** A plain query: the passages of a workspace that match a query. */
  search: (workspaceId: string, query: string) => ["search", workspaceId, query] as const,
  chat: ["chat"] as const,
  /** Every chat session list, all workspaces or one workspace. */
  chatSessionLists: ["chat", "sessions"] as const,
  /** Infinite, `CHAT_SESSION_LIST_PAGE_SIZE` per page. */
  chatSessions: (workspaceId: string | null) => ["chat", "sessions", workspaceId ?? "all"] as const,
  /** A plain query: one chat session with all of its messages. */
  chatSession: (id: string) => ["chat", "detail", id] as const,
  /** Mutation key for sending a message in one session, read via `useMutationState`. */
  chatSessionSend: (id: string) => ["chat", "detail", id, "send"] as const,
  meta: ["meta"] as const,
};

export const WORKSPACE_LIST_PAGE_SIZE = 20;
export const RECENT_WORKSPACES_COUNT = 3;
export const WORKSPACE_DOCUMENTS_PAGE_SIZE = 50;
export const DOCUMENT_CHUNKS_PAGE_SIZE = 50;
export const CHAT_SESSION_LIST_PAGE_SIZE = 20;
