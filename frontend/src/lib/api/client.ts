import { ApiError, NETWORK_ERROR_CODE, toApiError, toInvalidResponseError } from "./errors";

export const API_BASE_PATH = "/api/v1";
const HTTP_NO_CONTENT = 204;

export interface ApiRequestInit extends Omit<RequestInit, "body"> {
  /** Sent as JSON with the matching Content-Type header. */
  json?: unknown;
  body?: BodyInit | null;
}

export async function apiFetch<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const { json, headers, body, ...rest } = init;
  const requestHeaders = new Headers(headers);
  requestHeaders.set("Accept", "application/json");
  let requestBody = body;
  if (json !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
    requestBody = JSON.stringify(json);
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
