import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { readinessFromError } from "./readiness";

const degraded = {
  status: "unavailable",
  checks: {
    database: { status: "error", latency_ms: null },
    redis: { status: "ok", latency_ms: 0.4 },
  },
};

describe("readinessFromError", () => {
  it("reads the per-component report from a 503", () => {
    const error = new ApiError({ status: 503, code: "http_error", message: "", body: degraded });

    expect(readinessFromError(error)).toEqual(degraded);
  });

  it("ignores a 503 whose body is not a readiness report", () => {
    const error = new ApiError({ status: 503, code: "http_error", message: "", body: "<html>" });

    expect(readinessFromError(error)).toBeNull();
  });

  it("ignores other failures", () => {
    expect(
      readinessFromError(
        new ApiError({ status: 500, code: "internal_error", message: "", body: degraded }),
      ),
    ).toBeNull();
    expect(readinessFromError(new TypeError("boom"))).toBeNull();
    expect(readinessFromError(null)).toBeNull();
  });
});
