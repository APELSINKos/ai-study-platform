import { z } from "zod";

export const NETWORK_ERROR_CODE = "network_error";
export const HTTP_ERROR_CODE = "http_error";
const REQUEST_ID_HEADER = "X-Request-ID";

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
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetail[];
  readonly requestId: string | null;
  readonly body: unknown;

  constructor({
    status,
    code,
    message,
    details = [],
    requestId = null,
    body,
    cause,
  }: ApiErrorInit) {
    super(message, { cause });
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
    this.body = body;
  }
}

export async function toApiError(response: Response): Promise<ApiError> {
  const text = await response.text();
  const body = parseJson(text);
  const headerRequestId = response.headers.get(REQUEST_ID_HEADER);
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
    });
  }
  return new ApiError({
    status: response.status,
    code: HTTP_ERROR_CODE,
    message: response.statusText || `Request failed with status ${response.status}`,
    requestId: headerRequestId,
    body: body ?? text,
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
