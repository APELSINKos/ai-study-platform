import { describe, expect, it } from "vitest";

import { sessionParamFrom, workspaceParamFrom } from "./url-params";

const VALID_LOWER = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const VALID_UPPER = VALID_LOWER.toUpperCase();

describe("sessionParamFrom", () => {
  it("returns none when the parameter is absent or empty", () => {
    expect(sessionParamFrom(undefined)).toEqual({ kind: "none" });
    expect(sessionParamFrom("")).toEqual({ kind: "none" });
  });

  it("normalizes a valid UUID to lowercase", () => {
    expect(sessionParamFrom(VALID_LOWER)).toEqual({ kind: "valid", id: VALID_LOWER });
    expect(sessionParamFrom(VALID_UPPER)).toEqual({ kind: "valid", id: VALID_LOWER });
  });

  it.each([
    ["not-a-uuid"],
    [` ${VALID_LOWER} `],
    ["   "],
    ["../auth/me"],
    [[VALID_LOWER, VALID_UPPER]],
  ])("marks malformed or duplicated value %j as invalid", (value) => {
    expect(sessionParamFrom(value)).toEqual({ kind: "invalid" });
  });
});

describe("workspaceParamFrom", () => {
  it("normalizes a valid UUID to lowercase", () => {
    expect(workspaceParamFrom(VALID_LOWER)).toBe(VALID_LOWER);
    expect(workspaceParamFrom(VALID_UPPER)).toBe(VALID_LOWER);
  });

  it.each([[undefined], [""], ["not-a-uuid"], [` ${VALID_LOWER} `], [[VALID_LOWER, VALID_UPPER]]])(
    "returns null for absent or malformed value %j",
    (value) => {
      expect(workspaceParamFrom(value)).toBeNull();
    },
  );
});
