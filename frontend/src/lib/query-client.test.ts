import { describe, expect, it } from "vitest";

import { ApiError, NETWORK_ERROR_CODE } from "./api/errors";
import { shouldRetry } from "./query-client";

const clientError = new ApiError({ status: 404, code: "not_found", message: "Not found." });
const serverError = new ApiError({ status: 503, code: "http_error", message: "Unavailable." });
const networkError = new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "Offline." });

describe("shouldRetry", () => {
  it("never retries client errors", () => {
    expect(shouldRetry(0, clientError)).toBe(false);
  });

  it("retries server and network errors a limited number of times", () => {
    expect(shouldRetry(0, serverError)).toBe(true);
    expect(shouldRetry(1, networkError)).toBe(true);
    expect(shouldRetry(2, serverError)).toBe(false);
  });
});
