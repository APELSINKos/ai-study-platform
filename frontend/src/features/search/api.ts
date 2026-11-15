import { apiFetch } from "@/lib/api/client";
import type { SearchResults } from "@/lib/api/types";

/**
 * How many passages a search asks for. A search that returns this many may have left other
 * matching passages out.
 */
export const SEARCH_RESULT_LIMIT = 10;

/**
 * The passages of a workspace's ready documents that best match the query, the best first, by
 * the query's words and by embeddings together. `signal` stops the request once nobody waits for
 * its answer.
 */
export function searchWorkspace(
  workspaceId: string,
  query: string,
  signal?: AbortSignal,
): Promise<SearchResults> {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    q: query,
    limit: String(SEARCH_RESULT_LIMIT),
  });
  return apiFetch<SearchResults>(`/search?${params.toString()}`, { signal });
}
