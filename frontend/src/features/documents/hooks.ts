import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";
import type { ChunkOut, ChunkPage, DocumentOut, DocumentPage } from "@/lib/api/types";
import {
  DOCUMENT_CHUNKS_PAGE_SIZE,
  queryKeys,
  WORKSPACE_DOCUMENTS_PAGE_SIZE,
} from "@/lib/query-keys";

import {
  deleteDocument,
  fetchChunkPage,
  fetchDocument,
  fetchDocumentPage,
  retryDocument,
} from "./api";
import { DOCUMENT_NOT_FOUND_CODE } from "./error-message";
import { pollInterval } from "./status";

const FIRST_PAGE = 1;

type DocumentPages = InfiniteData<DocumentPage, number>;

/** The documents loaded so far, and how many the workspace holds in all. */
export interface LoadedDocuments {
  documents: DocumentOut[];
  total: number;
}

function nextPageAfter(
  lastPage: Pick<DocumentPage | ChunkPage, "page" | "page_size" | "total">,
): number | undefined {
  return lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined;
}

function allDocuments(data: DocumentPages | undefined): DocumentOut[] {
  return data?.pages.flatMap((page) => page.items) ?? [];
}

/**
 * The loaded pages as one list. Pages are offsets into a list ordered by upload, so a file
 * uploaded between two pages pushes a document onto the next page as well; the first copy stays.
 */
function uniqueDocuments(data: DocumentPages): DocumentOut[] {
  const seen = new Set<string>();
  return allDocuments(data).filter((document) => {
    if (seen.has(document.id)) {
      return false;
    }
    seen.add(document.id);
    return true;
  });
}

function loadedDocuments(data: DocumentPages): LoadedDocuments {
  const documents = uniqueDocuments(data);
  // The last page fetched has the latest total. A document deleted between two page requests
  // can still sit on an earlier page, so the total never drops below what is shown.
  return { documents, total: Math.max(data.pages.at(-1)?.total ?? 0, documents.length) };
}

function isSettledStatus(status: DocumentOut["status"]): boolean {
  return status === "ready" || status === "failed";
}

function invalidateWorkspaceStats(queryClient: QueryClient, workspaceId: string): void {
  // Refresh workspace stats (e.g. ready_count for "Ask in chat") without re-fetching documents.
  void queryClient.invalidateQueries({
    queryKey: queryKeys.workspace(workspaceId),
    exact: true,
  });
  void queryClient.invalidateQueries({ queryKey: queryKeys.workspaceList });
  void queryClient.invalidateQueries({ queryKey: queryKeys.recentWorkspaces });
}

function hasSettledStatusChange(
  previousItems: readonly DocumentOut[],
  nextItems: readonly DocumentOut[],
  isFirstPage: boolean,
): boolean {
  const previousById = new Map(previousItems.map((document) => [document.id, document.status]));
  return nextItems.some((document) => {
    const before = previousById.get(document.id);
    if (before !== undefined) {
      return isSettledStatus(before) !== isSettledStatus(document.status);
    }
    return isFirstPage && isSettledStatus(document.status);
  });
}

/** Every document of a workspace, a page at a time, asked for again while any is on its way. */
export function useWorkspaceDocuments(workspaceId: string) {
  const queryClient = useQueryClient();
  return useInfiniteQuery({
    queryKey: queryKeys.workspaceDocuments(workspaceId),
    queryFn: async ({ pageParam, signal }) => {
      const previousData = queryClient.getQueryData<DocumentPages>(
        queryKeys.workspaceDocuments(workspaceId),
      );
      const nextPage = await fetchDocumentPage(
        workspaceId,
        pageParam,
        WORKSPACE_DOCUMENTS_PAGE_SIZE,
        signal,
      );
      if (
        !signal.aborted &&
        previousData?.pages[pageParam - 1] !== undefined &&
        hasSettledStatusChange(allDocuments(previousData), nextPage.items, pageParam === FIRST_PAGE)
      ) {
        invalidateWorkspaceStats(queryClient, workspaceId);
      }
      return nextPage;
    },
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextPageAfter,
    select: loadedDocuments,
    refetchInterval: (query) => pollInterval(allDocuments(query.state.data), query.state.error),
  });
}

interface DocumentQueryOptions {
  /** False stops every request for the document, such as while it is being deleted. */
  enabled?: boolean;
}

/** One document for its own page, asked for again on the same rule as the lists. */
export function useDocument(id: string, { enabled = true }: DocumentQueryOptions = {}) {
  const queryClient = useQueryClient();
  const normalizedId = id.toLowerCase();
  return useQuery({
    // An address may spell the id in capitals; the list, the retry and the delete use the API's
    // lowercase spelling, and all of them must reach the same cache entry.
    queryKey: queryKeys.document(normalizedId),
    queryFn: async ({ signal }) => {
      const previous = queryClient.getQueryData<DocumentOut>(queryKeys.document(normalizedId));
      const next = await fetchDocument(id, signal);
      if (
        !signal.aborted &&
        previous !== undefined &&
        !isSettledStatus(previous.status) &&
        isSettledStatus(next.status)
      ) {
        invalidateWorkspaceStats(queryClient, next.workspace_id);
      }
      return next;
    },
    enabled,
    refetchInterval: (query) => {
      const document = query.state.data;
      return pollInterval(document === undefined ? [] : [document], query.state.error);
    },
  });
}

/** The fragments loaded so far, and how many the document has in all. */
interface LoadedChunks {
  chunks: ChunkOut[];
  total: number;
}

function loadedChunks(data: InfiniteData<ChunkPage, number>): LoadedChunks {
  return {
    chunks: data.pages.flatMap((page) => page.items),
    total: data.pages.at(-1)?.total ?? 0,
  };
}

/** A document's fragments in reading order, a page at a time, asked for once it is ready. */
export function useDocumentChunks(document: DocumentOut) {
  return useInfiniteQuery({
    queryKey: queryKeys.documentChunks(document.id),
    queryFn: ({ pageParam }) => fetchChunkPage(document.id, pageParam, DOCUMENT_CHUNKS_PAGE_SIZE),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextPageAfter,
    // The fragments are stored in the last step of processing, all at once.
    enabled: document.status === "ready",
    // A ready document's fragments never change, so loaded pages are never asked for again.
    staleTime: Infinity,
    select: loadedChunks,
  });
}

function includes(data: DocumentPages, id: string): boolean {
  return data.pages.some((page) => page.items.some((document) => document.id === id));
}

/** Puts a document's new state into the cached list of its workspace. */
function replaceCachedDocument(queryClient: QueryClient, updated: DocumentOut): void {
  queryClient.setQueryData<DocumentPages>(
    queryKeys.workspaceDocuments(updated.workspace_id),
    (data) =>
      data && {
        ...data,
        pages: data.pages.map((page) => ({
          ...page,
          items: page.items.map((document) => (document.id === updated.id ? updated : document)),
        })),
      },
  );
}

/** Takes a document out of the cached list of its workspace, so its row goes at once. */
function removeCachedDocument(queryClient: QueryClient, removed: DocumentOut): void {
  queryClient.setQueryData<DocumentPages>(
    queryKeys.workspaceDocuments(removed.workspace_id),
    (data) => {
      if (data === undefined || !includes(data, removed.id)) {
        return data;
      }
      return {
        ...data,
        pages: data.pages.map((page) => ({
          ...page,
          items: page.items.filter((document) => document.id !== removed.id),
          total: page.total - 1,
        })),
      };
    },
  );
}

/** Starts processing a failed or stalled document again. */
export function useRetryDocument(document: DocumentOut) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => retryDocument(document.id),
    onSuccess: (updated) => {
      // The row and the document's own page show the new status at once, and both start
      // asking for news again.
      replaceCachedDocument(queryClient, updated);
      queryClient.setQueryData(queryKeys.document(updated.id), updated);
    },
    onSettled: () => {
      // Also after a failure: a document retried or deleted elsewhere then shows as it is.
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
      void queryClient.invalidateQueries({ queryKey: queryKeys.document(document.id) });
    },
  });
}

export function useDeleteDocument(document: DocumentOut) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      try {
        await deleteDocument(document.id);
      } catch (error) {
        // Already deleted, from another tab for example: what the user asked for is done.
        if (!(error instanceof ApiError && error.code === DOCUMENT_NOT_FOUND_CODE)) {
          throw error;
        }
      }
    },
    onSuccess: () => {
      removeCachedDocument(queryClient, document);
      // Removed, not invalidated: a refetch could only find the document gone. The key also
      // holds its fragments.
      queryClient.removeQueries({ queryKey: queryKeys.document(document.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
      // Its passages may be among the results of the workspace's searches. A first search still
      // on its way may have been worked out before the delete, and invalidating alone would keep
      // its answer, so it is stopped first and sent again.
      const searches = queryKeys.workspaceSearches(document.workspace_id);
      void queryClient.cancelQueries({ queryKey: searches });
      void queryClient.invalidateQueries({ queryKey: searches });
    },
  });
}
