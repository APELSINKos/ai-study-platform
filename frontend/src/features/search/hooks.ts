import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query-keys";

import { searchWorkspace } from "./api";

/**
 * The passages of a workspace that match `query`; nothing is asked for while it is null. Each
 * search may be a paid embedding request and counts against a rate limit, so nothing is sent in
 * the background: no retries, no refresh when the tab is shown again or the browser is back
 * online, and an answer never goes stale. A search is asked for again when the user searches
 * again or a document of the workspace is deleted. Coming back to a search (Back, Forward, the
 * page opened again) shows the answer kept for it; a failed search has none and is asked for
 * again, as is one left off screen for more than five minutes (TanStack's default gcTime).
 */
export function useSearch(workspaceId: string, query: string | null) {
  const text = query ?? "";
  return useQuery({
    queryKey: queryKeys.search(workspaceId, text),
    queryFn: ({ signal }) => searchWorkspace(workspaceId, text, signal),
    enabled: query !== null,
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}
