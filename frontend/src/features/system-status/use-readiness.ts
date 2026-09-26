import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { ReadinessResponse } from "@/lib/api/types";

export const READINESS_QUERY_KEY = ["health", "ready"] as const;
export const READINESS_REFETCH_INTERVAL_MS = 15_000;

export function useReadiness() {
  return useQuery({
    queryKey: READINESS_QUERY_KEY,
    queryFn: () => apiFetch<ReadinessResponse>("/health/ready"),
    refetchInterval: READINESS_REFETCH_INTERVAL_MS,
    retry: false,
  });
}
