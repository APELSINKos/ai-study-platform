import { z } from "zod";

export const NETWORK_ERROR_CODE = "network_error";
export const HTTP_ERROR_CODE = "http_error";
export const INVALID_RESPONSE_CODE = "invalid_response";
const REQUEST_ID_HEADER = "X-Request-ID";
const RETRY_AFTER_HEADER = "Retry-After";

const errorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.array(z.object({ field: z.string().nullable(), message: z.string() })).default([]),
    request_id: z.string().nullable().optional(),
  }),
});

export interface ApiErrorDetail {
  field: string | null;
  message: string;
}

interface ApiErrorInit {
  status: number;
  code: string;
  message: string;
  details?: ApiErrorDetail[];
  requestId?: string | null;
  body?: unknown;
  cause?: unknown;
  retryAfterSeconds?: number | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetail[];
  readonly requestId: string | null;
  readonly body: unknown;
  readonly retryAfterSeconds: number | null;

  constructor({
    status,
    code,
    message,
    details = [],
    requestId = null,
    body,
    cause,
    retryAfterSeconds = null,
  }: ApiErrorInit) {
    super(message, { cause });
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
    this.body = body;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function parseRetryAfterSeconds(response: Response): number | null {
  const header = response.headers.get(RETRY_AFTER_HEADER);
  if (!header) {
    return null;
  }
  const seconds = Number(header);
  return Number.isFinite(seconds) ? seconds : null;
}

export async function toApiError(response: Response): Promise<ApiError> {
  const text = await response.text();
  const body = parseJson(text);
  const headerRequestId = response.headers.get(REQUEST_ID_HEADER);
  const retryAfterSeconds = parseRetryAfterSeconds(response);
  const envelope = errorEnvelopeSchema.safeParse(body);

  if (envelope.success) {
    const { code, message, details, request_id } = envelope.data.error;
    return new ApiError({
      status: response.status,
      code,
      message,
      details,
      requestId: request_id ?? headerRequestId,
      body,
      retryAfterSeconds,
    });
  }
  return new ApiError({
    status: response.status,
    code: HTTP_ERROR_CODE,
    message: response.statusText || `Request failed with status ${response.status}`,
    requestId: headerRequestId,
    body: body ?? text,
    retryAfterSeconds,
  });
}

export function toInvalidResponseError(response: Response, text: string, cause: unknown): ApiError {
  return new ApiError({
    status: response.status,
    code: INVALID_RESPONSE_CODE,
    message: "The API returned a response that was not valid JSON.",
    requestId: response.headers.get(REQUEST_ID_HEADER),
    body: text,
    cause,
  });
}

function parseJson(text: string): unknown {
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    // Not JSON (for example an HTML page from a proxy); the caller keeps the raw text instead.
    return undefined;
  }
}
