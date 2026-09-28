import { render, screen } from "@testing-library/react";
import type * as MotionModule from "motion/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { REVIEW_SEGMENTS } from "./curve";
import { ForgettingCurve } from "./forgetting-curve";

const motionPreference = vi.hoisted(() => ({ reduce: false }));

vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof MotionModule>()),
  useReducedMotion: () => motionPreference.reduce,
}));

function reviewCurveSegments(): SVGPathElement[] {
  const chart = screen.getByTestId("forgetting-curve");
  return [...chart.querySelectorAll<SVGPathElement>("path.stroke-pen")];
}

describe("ForgettingCurve", () => {
  beforeEach(() => {
    motionPreference.reduce = false;
  });

  it("waits for the reader to scroll before drawing the reviews", () => {
    render(<ForgettingCurve />);

    const segments = reviewCurveSegments();
    expect(segments).toHaveLength(REVIEW_SEGMENTS.length);
    for (const segment of segments) {
      expect(segment.getAttribute("stroke-dasharray")).toBe("0 1");
    }
  });

  it("is drawn complete when motion is reduced", () => {
    motionPreference.reduce = true;
    render(<ForgettingCurve />);

    expect(screen.getByTestId("forgetting-curve")).toHaveAttribute("data-static", "true");
    for (const segment of reviewCurveSegments()) {
      expect(segment.getAttribute("stroke-dasharray")).toBe("1 1");
    }
  });
});
