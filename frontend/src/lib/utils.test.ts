import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("lets a later class win over a conflicting earlier one", () => {
    expect(cn("bg-sheet px-2", "bg-pen")).toBe("px-2 bg-pen");
  });

  it("keeps a custom text size next to a text colour", () => {
    expect(cn("text-display", "text-ink")).toBe("text-display text-ink");
  });

  it("drops falsy values", () => {
    expect(cn("rounded-control", false, undefined, null, "")).toBe("rounded-control");
  });
});
