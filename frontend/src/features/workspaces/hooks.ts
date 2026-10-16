import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";
import type { WorkspaceOut, WorkspacePage, WorkspaceUpdateRequest } from "@/lib/api/types";
import { queryKeys, RECENT_WORKSPACES_COUNT, WORKSPACE_LIST_PAGE_SIZE } from "@/lib/query-keys";

import {
  createWorkspace,
  deleteWorkspace,
  fetchWorkspace,
  fetchWorkspacePage,
  updateWorkspace,
} from "./api";
import { WORKSPACE_NOT_FOUND_CODE } from "./error-message";

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

/** The few workspaces changed last, for the dashboard: one page, never more. */
export function useRecentWorkspaces() {
  return useQuery({
    queryKey: queryKeys.recentWorkspaces,
    queryFn: () => fetchWorkspacePage(FIRST_PAGE, RECENT_WORKSPACES_COUNT),
  });
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createWorkspace,
    onSuccess: () => {
      // Not awaited: the new workspace opens at once while the lists refresh behind it.
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
    },
  });
}

/** One workspace with the statistics of its documents, for its own page. */
export function useWorkspace(id: string) {
  return useQuery({
    // An address may spell the id in capitals; the edits and the delete use the API's lowercase
    // spelling, and all of them must reach the same cache entry.
    queryKey: queryKeys.workspace(id.toLowerCase()),
    queryFn: () => fetchWorkspace(id),
  });
}

export function useUpdateWorkspace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: WorkspaceUpdateRequest) => updateWorkspace(id, changes),
    onSuccess: (workspace) => {
      // The page shows the saved values at once rather than after the refetch below.
      queryClient.setQueryData(queryKeys.workspace(id), workspace);
    },
    onSettled: () => {
      // Also after a failure: a workspace deleted meanwhile then shows as not found.
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
    },
  });
}

export function useDeleteWorkspace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      try {
        await deleteWorkspace(id);
      } catch (error) {
        // Already deleted, from another tab for example: what the user asked for is done.
        if (!(error instanceof ApiError && error.code === WORKSPACE_NOT_FOUND_CODE)) {
          throw error;
        }
      }
    },
    onSuccess: () => {
      // Removed, not invalidated: a refetch could only find the workspace gone. The key also
      // holds the workspace's document list.
      queryClient.removeQueries({ queryKey: queryKeys.workspace(id) });
      // An invalidated list still shows its cached rows until the refetch lands, so a list off
      // screen would show the deleted workspace for a moment when the user returns to it; it
      // loads afresh instead. A list on screen (the user went back while waiting) is only
      // invalidated: removed, it would keep its rows and never refetch.
      queryClient.removeQueries({ queryKey: queryKeys.workspaceList, type: "inactive" });
      queryClient.removeQueries({ queryKey: queryKeys.recentWorkspaces, type: "inactive" });
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
    },
  });
}
