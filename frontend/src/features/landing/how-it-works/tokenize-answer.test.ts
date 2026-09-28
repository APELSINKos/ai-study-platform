import { describe, expect, it } from "vitest";

import { tokenizeAnswer } from "./tokenize-answer";

describe("tokenizeAnswer", () => {
  it("splits words and keeps punctuation after a source mark", () => {
    expect(tokenizeAnswer("Reviews slow forgetting [1], a lot [2].")).toEqual([
      { kind: "word", text: "Reviews" },
      { kind: "word", text: "slow" },
      { kind: "word", text: "forgetting" },
      { kind: "citation", number: 1, trailing: "," },
      { kind: "word", text: "a" },
      { kind: "word", text: "lot" },
      { kind: "citation", number: 2, trailing: "." },
    ]);
  });

  it("ignores extra whitespace and treats unfinished brackets as words", () => {
    expect(tokenizeAnswer("  see [x] \n here ")).toEqual([
      { kind: "word", text: "see" },
      { kind: "word", text: "[x]" },
      { kind: "word", text: "here" },
    ]);
  });
});
