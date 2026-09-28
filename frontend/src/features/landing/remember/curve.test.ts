import { describe, expect, it } from "vitest";

import {
  DAYS_SHOWN,
  END_RETENTION,
  FIRST_STABILITY_DAYS,
  PLOT,
  REVIEWS,
  REVIEW_SEGMENTS,
  retention,
  xOf,
  yOf,
} from "./curve";

const DAY = 1;
const WEEK = 7;

describe("forgetting curve", () => {
  it("matches the story told on the page", () => {
    // More than half is gone a day after the lecture, and about a fifth is left after a week.
    expect(retention(DAY, FIRST_STABILITY_DAYS)).toBeLessThan(0.5);
    expect(retention(WEEK, FIRST_STABILITY_DAYS)).toBeCloseTo(0.2, 2);
    expect(END_RETENTION.withReviews).toBeGreaterThan(END_RETENTION.withoutReview);
  });

  it("falls less after every review than after the one before", () => {
    const decays = [
      { length: REVIEWS[0]?.day ?? 0, stability: FIRST_STABILITY_DAYS },
      ...REVIEWS.map((review, index) => ({
        length: (REVIEWS[index + 1]?.day ?? DAYS_SHOWN) - review.day,
        stability: review.stabilityDays,
      })),
    ];
    const drops = decays.map(({ length, stability }) => 1 - retention(length, stability));
    for (let index = 1; index < drops.length; index++) {
      expect(drops[index]).toBeLessThan(drops[index - 1] ?? Infinity);
    }
  });

  it("has one drawable segment per decay, each review lifting back to the top", () => {
    expect(REVIEW_SEGMENTS).toHaveLength(REVIEWS.length + 1);
    for (const [index, review] of REVIEWS.entries()) {
      const lift = REVIEW_SEGMENTS[index]?.review;
      expect(lift?.x).toBeCloseTo(xOf(review.day), 1);
      expect(lift?.y).toBe(yOf(1));
    }
    expect(REVIEW_SEGMENTS.at(-1)?.review).toBeNull();
  });

  it("maps the plot corners", () => {
    expect(xOf(0)).toBe(PLOT.left);
    expect(yOf(1)).toBe(PLOT.top);
    expect(yOf(0)).toBe(PLOT.bottom);
  });
});
