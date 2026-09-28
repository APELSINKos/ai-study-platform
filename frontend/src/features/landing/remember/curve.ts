/*
 * Geometry of the forgetting-curve illustration. Retention decays exponentially towards a floor,
 * as in Ebbinghaus's savings curve; every review restores it and makes the next decay slower.
 * The numbers draw a believable picture, not a measurement.
 */

export const CHART_WIDTH = 600;
export const CHART_HEIGHT = 240;
/** The plot area inside the chart: `top` is everything remembered, `bottom` is nothing. */
export const PLOT = { left: 6, right: 594, top: 14, bottom: 226 } as const;
export const DAYS_SHOWN = 30;

/** Share of the material that stays even without any review. */
const FLOOR = 0.2;
/** How slowly memory fades after the lecture, in days. */
export const FIRST_STABILITY_DAYS = 0.9;

interface Review {
  day: number;
  /** How slowly memory fades after this review, in days. */
  stabilityDays: number;
}

const LAST_REVIEW: Review = { day: 16, stabilityDays: 40 };
export const REVIEWS: readonly Review[] = [
  { day: 1, stabilityDays: 2.4 },
  { day: 3, stabilityDays: 5.5 },
  { day: 7, stabilityDays: 14 },
  LAST_REVIEW,
];

const SAMPLES_PER_DAY = 8;
const MIN_SAMPLES = 12;

export interface ChartPoint {
  x: number;
  y: number;
}

export interface ReviewSegment {
  /** The decay after the lecture or a review, ending with the lift of the next review if any. */
  path: string;
  /** Where the next review puts retention back to the top; `null` for the last segment. */
  review: ChartPoint | null;
}

export function retention(daysSinceReview: number, stabilityDays: number): number {
  return FLOOR + (1 - FLOOR) * Math.exp(-daysSinceReview / stabilityDays);
}

export function xOf(day: number): number {
  return PLOT.left + (day / DAYS_SHOWN) * (PLOT.right - PLOT.left);
}

export function yOf(share: number): number {
  return PLOT.bottom - share * (PLOT.bottom - PLOT.top);
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}

function decayPoints(fromDay: number, toDay: number, stabilityDays: number): ChartPoint[] {
  const samples = Math.max(MIN_SAMPLES, Math.ceil((toDay - fromDay) * SAMPLES_PER_DAY));
  return Array.from({ length: samples + 1 }, (_, index) => {
    const day = fromDay + ((toDay - fromDay) * index) / samples;
    return { x: round(xOf(day)), y: round(yOf(retention(day - fromDay, stabilityDays))) };
  });
}

function toPath(points: ChartPoint[]): string {
  return points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x} ${point.y}`).join("");
}

/** Retention with no review at all. */
export const WITHOUT_REVIEW_PATH = toPath(decayPoints(0, DAYS_SHOWN, FIRST_STABILITY_DAYS));

const DECAYS = [
  { fromDay: 0, stabilityDays: FIRST_STABILITY_DAYS },
  ...REVIEWS.map((review) => ({ fromDay: review.day, stabilityDays: review.stabilityDays })),
];

/** Retention with reviews, one segment per decay so the segments can be drawn one by one. */
export const REVIEW_SEGMENTS: readonly ReviewSegment[] = DECAYS.map((decay, index) => {
  const nextReview = REVIEWS[index];
  const points = decayPoints(decay.fromDay, nextReview?.day ?? DAYS_SHOWN, decay.stabilityDays);
  if (!nextReview) {
    return { path: toPath(points), review: null };
  }
  const review = { x: round(xOf(nextReview.day)), y: round(yOf(1)) };
  return { path: toPath([...points, review]), review };
});

/** Retention at the right edge of the chart for each curve, where their labels sit. */
export const END_RETENTION = {
  withoutReview: retention(DAYS_SHOWN, FIRST_STABILITY_DAYS),
  withReviews: retention(DAYS_SHOWN - LAST_REVIEW.day, LAST_REVIEW.stabilityDays),
} as const;
