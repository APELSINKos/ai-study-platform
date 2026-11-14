import { describe, expect, it } from "vitest";

import { passageHref } from "./passage-href";

const DOCUMENT_ID = "00000000-0000-4000-9000-000000000001";

describe("passageHref", () => {
  it("opens the document's page at a passage, by the passage's place in the document", () => {
    expect(passageHref(DOCUMENT_ID, 12)).toBe(`/documents/${DOCUMENT_ID}?fragment=12`);
  });

  it("names the first passage as 0", () => {
    expect(passageHref(DOCUMENT_ID, 0)).toBe(`/documents/${DOCUMENT_ID}?fragment=0`);
  });

  it("keeps an odd id inside its own path segment", () => {
    expect(passageHref("../auth/me", 3)).toBe("/documents/..%2Fauth%2Fme?fragment=3");
  });
});
