import { describe, expect, it } from "vitest";

import {
  PHASE_LENGTH,
  PHASE_START,
  PHASES,
  hasReached,
  phaseAt,
  phaseWindow,
  stepOf,
} from "./timeline";

describe("timeline", () => {
  it("finishes each moving phase before the next one begins", () => {
    const moving = ["split", "map", "question"] as const;
    for (const phase of moving) {
      const next = PHASES[PHASES.indexOf(phase) + 1];
      expect(next).toBeDefined();
      if (next) {
        expect(phaseWindow(phase)[1]).toBeLessThanOrEqual(PHASE_START[next]);
      }
    }
    expect(PHASE_START.answer + PHASE_LENGTH).toBeLessThanOrEqual(1);
  });

  it("finds the phase for a scroll position", () => {
    expect(phaseAt(0)).toBe("page");
    expect(phaseAt(PHASE_START.map - 0.001)).toBe("split");
    expect(phaseAt(PHASE_START.map)).toBe("map");
    expect(phaseAt(1)).toBe("answer");
  });

  it("treats the page and its split as the first step", () => {
    expect(stepOf("page")).toBe("passages");
    expect(stepOf("split")).toBe("passages");
    expect(stepOf("question")).toBe("search");
  });

  it("knows which phases are already behind", () => {
    expect(hasReached("answer", "question")).toBe(true);
    expect(hasReached("map", "question")).toBe(false);
  });
});
