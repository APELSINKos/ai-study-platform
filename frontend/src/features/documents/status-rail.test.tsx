import { render } from "@testing-library/react";
import type * as MotionModule from "motion/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentStatus } from "@/lib/api/types";

import { StatusRail } from "./status-rail";

const motionPreference = vi.hoisted(() => ({ reduce: false }));

vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof MotionModule>()),
  useReducedMotion: () => motionPreference.reduce,
}));

function renderRail(status: DocumentStatus, moving = false): SVGSVGElement {
  const { container } = render(<StatusRail status={status} moving={moving} />);
  const rail = container.querySelector("svg");
  if (!rail) {
    throw new Error("The rail did not render.");
  }
  return rail;
}

/** Each stage as "stage:state", in the order the rail draws them. */
function stages(rail: SVGSVGElement): string[] {
  return Array.from(rail.querySelectorAll("[data-stage]")).map(
    (dot) => `${dot.getAttribute("data-stage")}:${dot.getAttribute("data-state")}`,
  );
}

function runningDot(rail: SVGSVGElement): Element | null {
  return rail.querySelector("[data-running]");
}

describe("StatusRail", () => {
  beforeEach(() => {
    motionPreference.reduce = false;
  });

  it("is a picture only: the stage is told in words beside it", () => {
    const rail = renderRail("processing", true);

    expect(rail).toHaveAttribute("aria-hidden", "true");
    expect(rail.textContent).toBe("");
  });

  it.each([
    ["uploaded", ["uploaded:current", "processing:ahead", "indexing:ahead", "ready:ahead"]],
    ["processing", ["uploaded:passed", "processing:current", "indexing:ahead", "ready:ahead"]],
    ["indexing", ["uploaded:passed", "processing:passed", "indexing:current", "ready:ahead"]],
    ["ready", ["uploaded:passed", "processing:passed", "indexing:passed", "ready:passed"]],
  ] as const)("marks the stages a %s document has passed", (status, expected) => {
    expect(stages(renderRail(status))).toEqual(expected);
  });

  it("draws a failed document leaving the rail after its upload", () => {
    const rail = renderRail("failed");

    expect(stages(rail)).toEqual([
      "uploaded:passed",
      "processing:skipped",
      "indexing:skipped",
      "ready:skipped",
    ]);
    expect(rail.querySelector("[data-failure]")).toHaveClass("fill-margin");
    expect(runningDot(rail)).toBeNull();
  });

  it("colours the stages of a ready document as done", () => {
    const rail = renderRail("ready");

    for (const dot of rail.querySelectorAll("[data-stage]")) {
      expect(dot).toHaveClass("fill-ok");
    }
    expect(runningDot(rail)).toBeNull();
  });

  it("runs a dot towards the next stage while the document moves on", () => {
    const rail = renderRail("processing", true);

    expect(runningDot(rail)).toHaveAttribute("data-running", "animated");
  });

  it("keeps the dot still between the stages when motion is reduced", () => {
    motionPreference.reduce = true;

    const rail = renderRail("processing", true);

    expect(runningDot(rail)).toHaveAttribute("data-running", "still");
  });

  it("has no running dot while the document waits", () => {
    expect(runningDot(renderRail("uploaded", false))).toBeNull();
    expect(runningDot(renderRail("indexing", false))).toBeNull();
  });
});
