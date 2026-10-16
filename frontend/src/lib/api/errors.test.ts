import { describe, expect, it } from "vitest";

import { ApiError, NETWORK_ERROR_CODE, isClientError } from "./errors";

describe("isClientError", () => {
  it.each([400, 401, 404, 409, 422, 429, 499])("is true for a %i answer", (status) => {
    expect(isClientError(new ApiError({ status, code: "x", message: "x" }))).toBe(true);
  });

  it.each([0, 399, 500, 503])("is false for a %i answer", (status) => {
    expect(isClientError(new ApiError({ status, code: NETWORK_ERROR_CODE, message: "x" }))).toBe(
      false,
    );
  });

  it("is false for anything that is not an API error", () => {
    expect(isClientError(new Error("boom"))).toBe(false);
    expect(isClientError(null)).toBe(false);
    expect(isClientError(undefined)).toBe(false);
  });
});
