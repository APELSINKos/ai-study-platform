import { describe, expect, it } from "vitest";

import { citationFixture } from "./test-fixtures";
import { tokenizeAnswerParagraphs } from "./tokenize-answer";

describe("tokenizeAnswerParagraphs", () => {
  it("splits paragraphs on blank lines and replaces mapped citation markers", () => {
    const c1 = citationFixture(1);
    const c2 = citationFixture(2);

    const paragraphs = tokenizeAnswerParagraphs(
      "First claim [1].\n\nSecond claim [1][2] and more.",
      [c1, c2],
    );

    expect(paragraphs).toEqual([
      [
        { kind: "text", text: "First claim " },
        { kind: "citation", citation: c1 },
        { kind: "text", text: "." },
      ],
      [
        { kind: "text", text: "Second claim " },
        { kind: "citation", citation: c1 },
        { kind: "citation", citation: c2 },
        { kind: "text", text: " and more." },
      ],
    ]);
  });

  it("leaves unmapped numbers like [2024] or [99] as plain text", () => {
    const c1 = citationFixture(1);

    const paragraphs = tokenizeAnswerParagraphs(
      "In [2024] Ebbinghaus notes [99] confirmed review helps [1].",
      [c1],
    );

    expect(paragraphs).toEqual([
      [
        { kind: "text", text: "In [2024] Ebbinghaus notes [99] confirmed review helps " },
        { kind: "citation", citation: c1 },
        { kind: "text", text: "." },
      ],
    ]);
  });

  it("keeps plain text untouched when there are no citations or blank input", () => {
    expect(tokenizeAnswerParagraphs("   \n\n   ", [])).toEqual([]);
    expect(tokenizeAnswerParagraphs("<b>plain</b> [1]", [])).toEqual([
      [{ kind: "text", text: "<b>plain</b> [1]" }],
    ]);
  });

  it("runs in linear time on hostile repeated brackets", () => {
    const c1 = citationFixture(1);
    const hostile = `${"[".repeat(100_000)}[1]`;
    const started = performance.now();

    const paragraphs = tokenizeAnswerParagraphs(hostile, [c1]);
    const elapsedMs = performance.now() - started;

    expect(elapsedMs).toBeLessThan(500);
    expect(paragraphs).toEqual([
      [
        { kind: "text", text: "[".repeat(100_000) },
        { kind: "citation", citation: c1 },
      ],
    ]);
  });
});
