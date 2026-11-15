import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query-keys";

import { searchWorkspace } from "./api";

/**
 * The passages of a workspace that match `query`; nothing is asked for while it is null. Each
 * search may be a paid embedding request and counts against a rate limit, so an answer is kept
 * and asked for again only on request, and a failed search is never tried again by itself.
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
