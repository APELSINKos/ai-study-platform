/*
 * The "How it works" story is pinned while the reader scrolls through a tall track. Scroll
 * progress through that track (0 to 1) decides which phase of the story is on screen.
 */

export const PHASES = ["page", "split", "map", "question", "answer"] as const;
export type Phase = (typeof PHASES)[number];

/** Where each phase begins, as a share of the track. */
export const PHASE_START: Record<Phase, number> = {
  page: 0,
  split: 0.08,
  map: 0.3,
  question: 0.52,
  answer: 0.72,
};

/** A phase animates over this share of the track, then holds still until the next one. */
export const PHASE_LENGTH = 0.18;

export const FINAL_PHASE: Phase = "answer";

/** The four numbered steps; the page and its split into passages are both step one. */
export const STEPS = ["passages", "map", "search", "answer"] as const;
export type Step = (typeof STEPS)[number];

const STEP_OF_PHASE: Record<Phase, Step> = {
  page: "passages",
  split: "passages",
  map: "map",
  question: "search",
  answer: "answer",
};

export function phaseAt(progress: number): Phase {
  let current: Phase = "page";
  for (const phase of PHASES) {
    if (progress >= PHASE_START[phase]) {
      current = phase;
    }
  }
  return current;
}

export function stepOf(phase: Phase): Step {
  return STEP_OF_PHASE[phase];
}

export function hasReached(current: Phase, target: Phase): boolean {
  return PHASES.indexOf(current) >= PHASES.indexOf(target);
}

/** Track positions between which a phase animates: `[start, end]`. */
export function phaseWindow(phase: Phase): [number, number] {
  const start = PHASE_START[phase];
  return [start, start + PHASE_LENGTH];
}

/** A point part-way through a phase window, e.g. `within("map", 0.5)` is its middle. */
export function within(phase: Phase, share: number): number {
  const [start, end] = phaseWindow(phase);
  return start + (end - start) * share;
}
