import { ApiError, NETWORK_ERROR_CODE, toApiError, toInvalidResponseError } from "./errors";
import { emitSessionExpired } from "./session-events";

export const API_BASE_PATH = "/api/v1";
const HTTP_NO_CONTENT = 204;
const HTTP_UNAUTHORIZED = 401;

const CSRF_COOKIE_NAME = "recall_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const REFRESH_PATH = "/auth/refresh";
/** Paths the refresh cycle must never intercept: they either issue or destroy the session. */
const REFRESH_EXEMPT_PATHS = new Set([
  "/auth/login",
  "/auth/register",
  REFRESH_PATH,
  "/auth/logout",
  "/auth/token",
]);
const REAUTH_ERROR_CODES = new Set(["token_expired", "not_authenticated"]);

export interface ApiRequestInit extends Omit<RequestInit, "body"> {
  /** Sent as JSON with the matching Content-Type header. */
  json?: unknown;
  body?: BodyInit | null;
}

let refreshPromise: Promise<boolean> | null = null;

function readCsrfToken(): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const prefix = `${CSRF_COOKIE_NAME}=`;
  const cookie = document.cookie.split("; ").find((entry) => entry.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : null;
}

async function rawFetch<T>(path: string, init: ApiRequestInit): Promise<T> {
  const { json, headers, body, ...rest } = init;
  const requestHeaders = new Headers(headers);
  requestHeaders.set("Accept", "application/json");
  let requestBody = body;
  if (json !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
    requestBody = JSON.stringify(json);
  }
  const method = (rest.method ?? "GET").toUpperCase();
  if (!SAFE_METHODS.has(method)) {
    const csrfToken = readCsrfToken();
    if (csrfToken) {
      requestHeaders.set(CSRF_HEADER_NAME, csrfToken);
    }
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_PATH}${path}`, {
      ...rest,
      headers: requestHeaders,
      body: requestBody,
      credentials: "same-origin",
    });
  } catch (cause) {
    throw new ApiError({
      status: 0,
      code: NETWORK_ERROR_CODE,
      message: "The API could not be reached.",
      cause,
    });
  }

  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === HTTP_NO_CONTENT) {
    return undefined as T;
  }
  const text = await response.text();
  try {
    return JSON.parse(text) as T;
  } catch (cause) {
    throw toInvalidResponseError(response, text, cause);
  }
}

/** One in-flight refresh at a time; concurrent callers await the same attempt. */
function refreshSession(): Promise<boolean> {
  refreshPromise ??= rawFetch(REFRESH_PATH, { method: "POST" })
    .then(() => true)
    .catch(() => false)
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

function needsRefresh(error: unknown, path: string): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === HTTP_UNAUTHORIZED &&
    REAUTH_ERROR_CODES.has(error.code) &&
    !REFRESH_EXEMPT_PATHS.has(path)
  );
}

export async function apiFetch<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  try {
    return await rawFetch<T>(path, init);
  } catch (error) {
    if (!needsRefresh(error, path)) {
      throw error;
    }
    const refreshed = await refreshSession();
    if (!refreshed) {
      emitSessionExpired();
      throw error;
    }
    return rawFetch<T>(path, init);
  }
}
