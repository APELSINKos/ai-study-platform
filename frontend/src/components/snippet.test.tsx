import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SnippetPart } from "@/lib/api/types";

import { Snippet } from "./snippet";

function renderSnippet(parts: SnippetPart[]) {
  render(
    <p>
      <Snippet parts={parts} />
    </p>,
  );
  return screen.getByRole("paragraph");
}

function marked(): string[] {
  return Array.from(document.querySelectorAll("mark")).map((mark) => mark.textContent ?? "");
}

describe("Snippet", () => {
  it("shows the words in order and marks the ones the query matched", () => {
    const paragraph = renderSnippet([
      { text: "Chloroplasts turn ", highlighted: false },
      { text: "light", highlighted: true },
      { text: " into sugar … the ", highlighted: false },
      { text: "light", highlighted: true },
      { text: " reactions split water.", highlighted: false },
    ]);

    expect(paragraph.textContent).toBe(
      "Chloroplasts turn light into sugar … the light reactions split water.",
    );
    expect(marked()).toEqual(["light", "light"]);
  });

  it("marks nothing when the query matched no word", () => {
    const paragraph = renderSnippet([
      { text: "The Calvin cycle fixes carbon.", highlighted: false },
    ]);

    expect(paragraph.textContent).toBe("The Calvin cycle fixes carbon.");
    expect(marked()).toEqual([]);
  });

  it("shows nothing for a snippet without parts", () => {
    const paragraph = renderSnippet([]);

    expect(paragraph).toBeEmptyDOMElement();
  });

  it("shows markup in a part as plain text, marked or not", () => {
    const markup = "<img src=x onerror=alert(1)>";
    const paragraph = renderSnippet([
      { text: `${markup} before `, highlighted: false },
      { text: markup, highlighted: true },
    ]);

    expect(paragraph.textContent).toBe(`${markup} before ${markup}`);
    expect(marked()).toEqual([markup]);
    expect(document.querySelector("img")).toBeNull();
  });
});
