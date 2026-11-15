import { describe, expect, it } from "vitest";

import { fragmentFrom } from "./fragment-param";

describe("fragmentFrom", () => {
  it.each([
    ["0", 0],
    ["12", 12],
    ["007", 7],
    ["999999", 999_999],
  ])("reads the fragment %s as its place in the document", (value, place) => {
    expect(fragmentFrom(value)).toBe(place);
  });

  it.each([
    ["no parameter", undefined],
    ["an empty one", ""],
    ["a negative number", "-1"],
    ["a fraction", "1.5"],
    ["an exponent", "1e3"],
    ["a hexadecimal number", "0x1"],
    ["more than six digits", "1234567"],
    ["a sign", "+1"],
    ["spaces around the digits", " 1 "],
    ["a line break after them", "1\n"],
    ["a repeated parameter", ["1", "2"]],
  ])("opens no fragment for %s", (_, value) => {
    expect(fragmentFrom(value)).toBeNull();
  });
});
