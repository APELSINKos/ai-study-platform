import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";

import type { DocumentOut, DocumentPage } from "@/lib/api/types";
import { queryKeys, WORKSPACE_DOCUMENTS_PAGE_SIZE } from "@/lib/query-keys";

import { fetchDocumentPage } from "./api";
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
