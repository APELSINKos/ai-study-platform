import type { MotionValue } from "motion/react";

import { within, type Phase } from "./timeline";

/** Scroll progress through the pinned track, from 0 to 1. */
export type Progress = MotionValue<number>;
type Share = readonly [number, number];

/** When each thing happens inside its phase, as shares of that phase (see `within`). */
export const CUE = {
  pageFades: [0, 0.45],
  cardFramesAppear: [0, 0.5],
  gridAppears: [0, 0.5],
  cardsFade: [0.6, 0.9],
  pointsDim: [0, 0.4],
  questionDot: [0, 0.25],
  questionRing: [0.1, 0.35],
  linkDraw: [0.3, 0.7],
  badgesAppear: [0.8, 1],
} as const satisfies Record<string, Share>;

export function cue(phase: Phase, [from, to]: Share): [number, number] {
  return [within(phase, from), within(phase, to)];
}

/** Share of the way from `start` to `end`, held at 0 before it and at 1 after it. */
export function ramp(value: number, start: number, end: number): number {
  return Math.min(1, Math.max(0, (value - start) / (end - start)));
}
