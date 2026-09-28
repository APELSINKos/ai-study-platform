import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { stubIntersectionObserver } from "@/test/intersection-observer";

import { LazyMount } from "./lazy-mount";

describe("LazyMount", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps its box but mounts the content only once it comes near the viewport", () => {
    const viewport = stubIntersectionObserver();
    const { container } = render(
      <LazyMount className="h-40">
        <p>Below the fold</p>
      </LazyMount>,
    );

    expect(container.firstElementChild).toHaveClass("h-40");
    expect(screen.queryByText("Below the fold")).not.toBeInTheDocument();

    act(() => viewport.revealAll());

    expect(screen.getByText("Below the fold")).toBeInTheDocument();
  });
});
