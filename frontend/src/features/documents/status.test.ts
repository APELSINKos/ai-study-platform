import { describe, expect, it } from "vitest";

import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";

import {
  ACTIVE_POLL_INTERVAL_MS,
  STALLED_POLL_INTERVAL_MS,
  documentProgress,
  pollInterval,
  tallyDocuments,
} from "./status";
import { documentFixture, readyDocumentFixture } from "./test-fixtures";

const notFound = new ApiError({ status: 404, code: "workspace_not_found", message: "x" });
const sessionEnded = new ApiError({ status: 401, code: "not_authenticated", message: "x" });
const serverError = new ApiError({ status: 503, code: "http_error", message: "x" });
const offline = new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" });

const processing = documentFixture(1, { status: "processing" });
const stalled = documentFixture(2, { status: "indexing", can_retry: true });
const ready = readyDocumentFixture(3);
const failed = documentFixture(4, { status: "failed", error_code: "no_text", can_retry: true });

describe("pollInterval", () => {
  it("does not ask again for an empty list", () => {
    expect(pollInterval([], null)).toBe(false);
  });

  it("does not ask again once every document is ready or failed", () => {
    expect(pollInterval([ready, failed], null)).toBe(false);
  });

  it.each(["uploaded", "processing", "indexing"] as const)(
    "asks every two seconds while a document is %s",
    (status) => {
      expect(pollInterval([ready, documentFixture(5, { status })], null)).toBe(
        ACTIVE_POLL_INTERVAL_MS,
      );
      expect(ACTIVE_POLL_INTERVAL_MS).toBe(2000);
    },
  );

  it("asks less often when every document in progress has stalled", () => {
    expect(pollInterval([stalled, ready, failed], null)).toBe(STALLED_POLL_INTERVAL_MS);
    expect(STALLED_POLL_INTERVAL_MS).toBe(15000);
  });

  it("keeps the short interval while one document in progress still moves", () => {
    expect(pollInterval([stalled, processing], null)).toBe(ACTIVE_POLL_INTERVAL_MS);
  });

  it.each([
    ["a missing workspace", notFound],
    ["an ended session", sessionEnded],
  ])("stops after %s, whatever the cached documents say", (_, error) => {
    expect(pollInterval([processing], error)).toBe(false);
  });

  it.each([
    ["a server failure", serverError],
    ["a lost connection", offline],
  ])("keeps asking after %s", (_, error) => {
    expect(pollInterval([processing], error)).toBe(ACTIVE_POLL_INTERVAL_MS);
  });
});

describe("documentProgress", () => {
  it.each(["uploaded", "processing", "indexing"] as const)("follows a %s document", (status) => {
    expect(documentProgress(documentFixture(1, { status }))).toEqual({
      kind: "active",
      stage: status,
      note: null,
    });
  });

  it("marks a ready document", () => {
    expect(documentProgress(ready)).toEqual({ kind: "ready" });
  });

  it("names why a document failed", () => {
    expect(documentProgress(failed)).toEqual({ kind: "failed", errorCode: "no_text" });
  });

  it("calls a failure without a code an internal error", () => {
    expect(documentProgress(documentFixture(1, { status: "failed" }))).toEqual({
      kind: "failed",
      errorCode: "internal_error",
    });
  });

  it("knows an automatic retry is coming after the AI service did not answer", () => {
    expect(
      documentProgress(documentFixture(1, { status: "uploaded", error_code: "ai_unavailable" })),
    ).toEqual({ kind: "active", stage: "uploaded", note: "retryPending" });
  });

  it.each(["uploaded", "processing", "indexing"] as const)(
    "notes that a %s document has stalled once it can be retried",
    (status) => {
      expect(documentProgress(documentFixture(1, { status, can_retry: true }))).toEqual({
        kind: "active",
        stage: status,
        note: "stalled",
      });
    },
  );

  it("treats a pending retry that has stalled as stalled", () => {
    expect(
      documentProgress(
        documentFixture(1, { status: "uploaded", error_code: "ai_unavailable", can_retry: true }),
      ),
    ).toEqual({ kind: "active", stage: "uploaded", note: "stalled" });
  });
});

describe("tallyDocuments", () => {
  it("counts the documents in progress, ready and failed", () => {
    expect(tallyDocuments([processing, stalled, ready, failed, readyDocumentFixture(6)])).toEqual({
      active: 2,
      ready: 2,
      failed: 1,
    });
  });

  it("counts nothing in an empty list", () => {
    expect(tallyDocuments([])).toEqual({ active: 0, ready: 0, failed: 0 });
  });
});
