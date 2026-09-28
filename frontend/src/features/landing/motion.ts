import type { Transition } from "motion/react";

/*
 * Motion vocabulary of the landing page. Pen and paper move quickly and settle softly, so almost
 * everything uses one ease-out curve; only the flashcard flip gets a spring, like a real card.
 */

/** Same curve as the `--ease-out-soft` token in globals.css. */
export const PEN_EASE = [0.22, 1, 0.36, 1] as const;

export const DURATION = {
  /** A card leaving the deck or the next one arriving. */
  deal: 0.35,
} as const;

export const FLIP_SPRING: Transition = { type: "spring", stiffness: 260, damping: 26, mass: 0.9 };

/** Reduced motion: every change applies at once. */
export const INSTANT: Transition = { duration: 0 };
