import { describe, expect, it } from "vitest";

import { isBuiltInModel } from "./models";

describe("isBuiltInModel", () => {
  it.each(["mock-hashing-v1", "mock-heuristic-v1"])("knows %s as built in", (model) => {
    expect(isBuiltInModel(model)).toBe(true);
  });

  it.each(["text-embedding-3-small", "nomic-embed-text", "gpt-4o-mini", "a-mock-model"])(
    "knows %s as a real model",
    (model) => {
      expect(isBuiltInModel(model)).toBe(false);
    },
  );

  it("knows no model when none is named", () => {
    expect(isBuiltInModel(null)).toBe(false);
  });
});
