import { z } from "zod";

import { ApiError } from "@/lib/api/errors";
import type { ReadinessResponse } from "@/lib/api/types";

const HTTP_SERVICE_UNAVAILABLE = 503;

const readinessSchema: z.ZodType<ReadinessResponse> = z.object({
  status: z.enum(["ok", "unavailable"]),
  checks: z.record(
    z.string(),
    z.object({
      status: z.enum(["ok", "error"]),
      latency_ms: z.number().nullable().optional(),
    }),
  ),
});

/** The backend answers 503 with a full readiness report; keep it so the UI can name what is down. */
export function readinessFromError(error: unknown): ReadinessResponse | null {
  if (!(error instanceof ApiError) || error.status !== HTTP_SERVICE_UNAVAILABLE) {
    return null;
  }
  const parsed = readinessSchema.safeParse(error.body);
  return parsed.success ? parsed.data : null;
}
