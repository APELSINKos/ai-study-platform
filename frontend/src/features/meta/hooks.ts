import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query-keys";

import { fetchMeta } from "./api";

/** Upload limits, accepted file types and the AI mode. They change only with a server restart. */
export function useMeta() {
  return useQuery({
    queryKey: queryKeys.meta,
    queryFn: fetchMeta,
    staleTime: Infinity,
  });
}
