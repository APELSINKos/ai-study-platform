"use client";

import {
  motion,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from "motion/react";
import { useId, useRef } from "react";

import {
  CHART_HEIGHT,
  CHART_WIDTH,
  PLOT,
  REVIEW_SEGMENTS,
  WITHOUT_REVIEW_PATH,
  yOf,
  type ReviewSegment,
} from "./curve";

type Progress = MotionValue<number>;

/** Scroll progress over which the curve without review is drawn. */
const WITHOUT_REVIEW_WINDOW = [0, 0.3] as const;
/** The curve with reviews is drawn segment by segment across this part of the scroll. */
const REVIEWS_FROM = 0.25;
const REVIEWS_TO = 0.95;
const DOT_POP = 0.04;
/** A path is hidden until it starts drawing, so its round cap does not show as a dot. */
const APPEAR = 0.005;

const CURVE_STROKE = 2.5;
const DOT_RADIUS = 5;
const DASH = "6 6";

/**
 * The forgetting curve, drawn as the reader scrolls it into view: first the fall without review,
 * then the saw-tooth of reviews, each dot lifting the curve back to the top. With reduced motion
 * it is drawn complete.
 */
export function ForgettingCurve() {
  const ref = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion() ?? false;
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.9", "end 0.55"] });
  const finished = useMotionValue(1);
  const progress = reduceMotion ? finished : scrollYProgress;
  const segmentShare = (REVIEWS_TO - REVIEWS_FROM) / REVIEW_SEGMENTS.length;

  return (
    <div
      ref={ref}
      data-testid="forgetting-curve"
      data-static={reduceMotion || undefined}
      className="size-full"
    >
      <svg
        aria-hidden
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        className="size-full overflow-visible"
      >
        <line
          x1={PLOT.left}
          x2={PLOT.right}
          y1={yOf(1)}
          y2={yOf(1)}
          className="stroke-rule"
          strokeDasharray={DASH}
        />
        <line
          x1={PLOT.left}
          x2={PLOT.right}
          y1={PLOT.bottom}
          y2={PLOT.bottom}
          className="stroke-rule-strong"
        />
        <WithoutReview progress={progress} />
        {REVIEW_SEGMENTS.map((segment, index) => {
          const from = REVIEWS_FROM + index * segmentShare;
          return (
            <Segment
              key={segment.path}
              segment={segment}
              from={from}
              to={from + segmentShare}
              progress={progress}
            />
          );
        })}
      </svg>
    </div>
  );
}

function WithoutReview({ progress }: { progress: Progress }) {
  const clipId = useId();
  // A dashed line cannot be drawn with pathLength (both use the dash array), so it is uncovered.
  const scaleX = useTransform(progress, [...WITHOUT_REVIEW_WINDOW], [0, 1]);
  return (
    <>
      <clipPath id={clipId}>
        <motion.rect width={CHART_WIDTH} height={CHART_HEIGHT} style={{ scaleX, originX: 0 }} />
      </clipPath>
      <path
        d={WITHOUT_REVIEW_PATH}
        clipPath={`url(#${clipId})`}
        fill="none"
        className="stroke-ink-soft"
        strokeWidth={2}
        strokeDasharray={DASH}
      />
    </>
  );
}

function Segment({
  segment,
  from,
  to,
  progress,
}: {
  segment: ReviewSegment;
  from: number;
  to: number;
  progress: Progress;
}) {
  const pathLength = useTransform(progress, [from, to], [0, 1]);
  const opacity = useTransform(progress, [from, from + APPEAR], [0, 1]);
  const dotScale = useTransform(progress, [to - APPEAR, to + DOT_POP], [0, 1]);
  return (
    <>
      <motion.path
        d={segment.path}
        fill="none"
        className="stroke-pen"
        strokeWidth={CURVE_STROKE}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ pathLength, opacity }}
      />
      {segment.review ? (
        <motion.circle
          cx={segment.review.x}
          cy={segment.review.y}
          r={DOT_RADIUS}
          className="fill-pen stroke-sheet"
          strokeWidth={2}
          style={{ scale: dotScale }}
        />
      ) : null}
    </>
  );
}
