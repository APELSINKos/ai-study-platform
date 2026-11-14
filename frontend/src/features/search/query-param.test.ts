import { describe, expect, it } from "vitest";

import { searchQueryFrom } from "./query-param";

describe("searchQueryFrom", () => {
  it("reads the query of the address without the spaces around it", () => {
    expect(searchQueryFrom("  light reactions ")).toBe("light reactions");
  });

  it.each([
    ["no parameter", undefined],
    ["an empty one", ""],
    ["spaces only", "   "],
    ["a repeated one", ["light", "glucose"]],
  ])("starts no search for %s", (_, value) => {
    expect(searchQueryFrom(value)).toBeNull();
  });
});
