import { QueryClient } from "@tanstack/react-query";

import { isClientError } from "./api/errors";

const DEFAULT_STALE_TIME_MS = 30_000;
const MAX_RETRIES = 2;

export function shouldRetry(failureCount: number, error: unknown): boolean {
  return !isClientError(error) && failureCount < MAX_RETRIES;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: DEFAULT_STALE_TIME_MS, retry: shouldRetry },
      mutations: { retry: false },
    },
  });
}
