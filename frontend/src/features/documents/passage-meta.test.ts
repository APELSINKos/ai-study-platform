import { describe, expect, it } from "vitest";

import { headingBelowTitle, pageRange, type PageRangeFormat } from "./passage-meta";

const formatPages: PageRangeFormat = {
  page: (page) => `Page ${page}`,
  pages: (start, end) => `Pages ${start}–${end}`,
};

describe("headingBelowTitle", () => {
  it("returns null when the passage has no heading", () => {
    expect(headingBelowTitle({ document_title: "Cell biology", heading: null })).toBeNull();
  });

  it("returns null when the heading repeats only the document title", () => {
    expect(
      headingBelowTitle({ document_title: "Cell biology", heading: "Cell biology" }),
    ).toBeNull();
  });

  it("strips the leading document title and separator from a heading path", () => {
    expect(
      headingBelowTitle({
        document_title: "Cell biology",
        heading: "Cell biology › Photosynthesis › Light reactions",
      }),
    ).toBe("Photosynthesis › Light reactions");
  });

  it("keeps headings that merely share a prefix with the title", () => {
    expect(
      headingBelowTitle({ document_title: "Cell biology", heading: "Cell biology basics" }),
    ).toBe("Cell biology basics");
  });

  it("keeps headings unrelated to the document title", () => {
    expect(headingBelowTitle({ document_title: "Lecture 1", heading: "Glycolysis" })).toBe(
      "Glycolysis",
    );
  });
});

describe("pageRange", () => {
  it("returns null when page_start is null", () => {
    expect(pageRange({ page_start: null, page_end: null }, formatPages)).toBeNull();
    expect(pageRange({ page_start: null, page_end: 5 }, formatPages)).toBeNull();
  });

  it("formats a single page when page_end matches or is null", () => {
    expect(pageRange({ page_start: 3, page_end: 3 }, formatPages)).toBe("Page 3");
    expect(pageRange({ page_start: 3, page_end: null }, formatPages)).toBe("Page 3");
  });

  it("formats a range when page_end differs from page_start", () => {
    expect(pageRange({ page_start: 4, page_end: 6 }, formatPages)).toBe("Pages 4–6");
  });
});
