import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";

import type { WorkspaceOut, WorkspacePage } from "@/lib/api/types";
import { queryKeys, WORKSPACE_LIST_PAGE_SIZE } from "@/lib/query-keys";

import { fetchWorkspacePage } from "./api";

const FIRST_PAGE = 1;

function nextPageAfter(lastPage: WorkspacePage): number | undefined {
  return lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined;
}

/**
 * The loaded pages as one list. Pages are offsets into a list ordered by the last change, so a
 * workspace updated between two pages can arrive twice; the first copy stays.
 */
function uniqueWorkspaces(data: InfiniteData<WorkspacePage, number>): WorkspaceOut[] {
  const seen = new Set<string>();
  return data.pages
    .flatMap((page) => page.items)
    .filter((workspace) => {
      if (seen.has(workspace.id)) {
        return false;
      }
      seen.add(workspace.id);
      return true;
    });
}

/** Every workspace of the user, loaded a page at a time. */
export function useWorkspaceList() {
  return useInfiniteQuery({
    queryKey: queryKeys.workspaceList,
    queryFn: ({ pageParam }) => fetchWorkspacePage(pageParam, WORKSPACE_LIST_PAGE_SIZE),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextPageAfter,
    select: uniqueWorkspaces,
  });
}
