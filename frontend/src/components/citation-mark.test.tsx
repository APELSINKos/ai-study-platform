import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CitationMark } from "./citation-mark";

describe("CitationMark", () => {
  it("renders the citation number and keeps a forced-colors outline", () => {
    render(<CitationMark number={3} data-testid="mark" />);

    const mark = screen.getByTestId("mark");
    expect(mark).toHaveTextContent("3");
    expect(mark).toHaveClass("border", "border-transparent", "forced-colors:border-[ButtonBorder]");
  });
});
