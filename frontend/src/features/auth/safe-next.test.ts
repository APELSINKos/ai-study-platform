import { describe, expect, it } from "vitest";

import { safeNext } from "./safe-next";

describe("safeNext", () => {
  it("rejects an absolute URL to another origin", () => {
    expect(safeNext("https://evil.example")).toBeNull();
  });

  it("rejects a protocol-relative URL", () => {
    expect(safeNext("//evil.example")).toBeNull();
  });

  it("rejects a backslash used to disguise a protocol-relative URL", () => {
    expect(safeNext("/\\evil")).toBeNull();
  });

  it("rejects a javascript: URL", () => {
    expect(safeNext("javascript:alert(1)")).toBeNull();
  });

  it("rejects a percent-encoded protocol-relative URL once decoded by the caller", () => {
    expect(safeNext(decodeURIComponent("%2F%2Fevil.example"))).toBeNull();
  });

  it("rejects a value carrying control characters", () => {
    expect(safeNext("/dashboard\n/evil")).toBeNull();
  });

  it("allows a same-origin absolute path with a query string", () => {
    expect(safeNext("/dashboard?x=1")).toBe("/dashboard?x=1");
  });

  it("rejects null, undefined and empty values", () => {
    expect(safeNext(null)).toBeNull();
    expect(safeNext(undefined)).toBeNull();
    expect(safeNext("")).toBeNull();
  });

  it.each([
    ["/.//evil.example"],
    ["/..//evil.example"],
    ["/a/../..//evil.example"],
    ["/%2e%2e//evil.example"],
  ])("rejects a dotted path a browser resolves to a protocol-relative URL: %s", (value) => {
    expect(safeNext(value)).toBeNull();
  });

  it("normalises a path with a dot segment to the path it resolves to", () => {
    expect(safeNext("/dashboard/../settings?x=1#y")).toBe("/settings?x=1#y");
  });
});
