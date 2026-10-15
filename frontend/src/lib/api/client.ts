import { CSRF_COOKIE_NAME } from "@/features/auth/constants";

import { ApiError, NETWORK_ERROR_CODE, toApiError, toInvalidResponseError } from "./errors";
import { emitSessionExpired } from "./session-events";

export const API_BASE_PATH = "/api/v1";
const HTTP_NO_CONTENT = 204;
const HTTP_UNAUTHORIZED = 401;
const JSON_MEDIA_TYPE = "application/json";
const ANY_MEDIA_TYPE = "*/*";

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
const REAUTH_ERROR_CODES = new Set(["token_expired", "not_authenticated", "invalid_token"]);

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

/** One attempt. A failed response becomes an ApiError; a successful one comes back unread. */
async function sendRequest(path: string, init: ApiRequestInit, accept: string): Promise<Response> {
  const { json, headers, body, ...rest } = init;
  const requestHeaders = new Headers(headers);
  requestHeaders.set("Accept", accept);
  let requestBody = body;
  if (json !== undefined) {
    requestHeaders.set("Content-Type", JSON_MEDIA_TYPE);
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
  return response;
}

async function readJson<T>(response: Response): Promise<T> {
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
  refreshPromise ??= sendRequest(REFRESH_PATH, { method: "POST" }, JSON_MEDIA_TYPE)
    .then((response) => readJson<unknown>(response))
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

/** Sends the request and, if the access token was rejected, once more after a session refresh. */
async function sendWithSessionRefresh(
  path: string,
  init: ApiRequestInit,
  accept: string,
): Promise<Response> {
  try {
    return await sendRequest(path, init, accept);
  } catch (error) {
    if (!needsRefresh(error, path)) {
      throw error;
    }
    const refreshed = await refreshSession();
    if (!refreshed) {
      emitSessionExpired();
      throw error;
    }
    return sendRequest(path, init, accept);
  }
}

export async function apiFetch<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  return readJson<T>(await sendWithSessionRefresh(path, init, JSON_MEDIA_TYPE));
}

/** For downloads: the request handling of `apiFetch`, with the body read as a Blob instead. */
export async function apiFetchBlob(path: string): Promise<Blob> {
  const response = await sendWithSessionRefresh(path, {}, ANY_MEDIA_TYPE);
  return response.blob();
}
