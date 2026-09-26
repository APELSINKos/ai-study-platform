import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./api/errors";

const DEFAULT_STALE_TIME_MS = 30_000;
const MAX_RETRIES = 2;
const FIRST_CLIENT_ERROR = 400;
const FIRST_SERVER_ERROR = 500;

export function shouldRetry(failureCount: number, error: unknown): boolean {
  const isClientError =
    error instanceof ApiError &&
    error.status >= FIRST_CLIENT_ERROR &&
    error.status < FIRST_SERVER_ERROR;
  return !isClientError && failureCount < MAX_RETRIES;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: DEFAULT_STALE_TIME_MS, retry: shouldRetry },
      mutations: { retry: false },
    },
  });
}
