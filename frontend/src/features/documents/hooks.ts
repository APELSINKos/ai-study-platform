import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";
import type { DocumentOut, DocumentPage } from "@/lib/api/types";
import { queryKeys, WORKSPACE_DOCUMENTS_PAGE_SIZE } from "@/lib/query-keys";

import { deleteDocument, fetchDocumentPage, retryDocument } from "./api";
import { DOCUMENT_NOT_FOUND_CODE } from "./error-message";
import { pollInterval } from "./status";

const FIRST_PAGE = 1;

type DocumentPages = InfiniteData<DocumentPage, number>;

/** The documents loaded so far, and how many the workspace holds in all. */
export interface LoadedDocuments {
  documents: DocumentOut[];
  total: number;
}

function nextPageAfter(lastPage: DocumentPage): number | undefined {
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

/** Every document of a workspace, a page at a time, asked for again while any is on its way. */
export function useWorkspaceDocuments(workspaceId: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.workspaceDocuments(workspaceId),
    queryFn: ({ pageParam }) =>
      fetchDocumentPage(workspaceId, pageParam, WORKSPACE_DOCUMENTS_PAGE_SIZE),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextPageAfter,
    select: loadedDocuments,
    refetchInterval: (query) => pollInterval(allDocuments(query.state.data), query.state.error),
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
      // The row shows the new status at once, and the list starts asking for news again.
      replaceCachedDocument(queryClient, updated);
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
    },
  });
}
