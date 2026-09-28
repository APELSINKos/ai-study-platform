import { motion, useTransform } from "motion/react";

import { CitationMark } from "./citation-mark";
import { CUE, cue, ramp, type Progress } from "./map-cues";
import {
  MAP_HEIGHT,
  MAP_WIDTH,
  PEN_STROKE,
  QUESTION_POINT,
  QUESTION_RADIUS,
  QUESTION_RING_RADIUS,
  SOURCE_BADGE_OFFSET,
  type Citation,
  type Point,
} from "./map-geometry";

/** The second link starts this share of the phase after the first, like a pen drawing twice. */
const LINK_STAGGER = 0.15;
/** A link is hidden until it starts drawing, so its round cap does not show as a dot. */
const LINK_APPEAR = 0.005;

/** The question lands on the map as a pen dot inside a drawn ring. */
export function QuestionPoint({ progress }: { progress: Progress }) {
  const scale = useTransform(progress, cue("question", CUE.questionDot), [0, 1]);
  const ringScale = useTransform(progress, cue("question", CUE.questionRing), [0, 1]);
  return (
    <>
      <motion.circle
        cx={QUESTION_POINT.x}
        cy={QUESTION_POINT.y}
        r={QUESTION_RING_RADIUS}
        fill="none"
        className="stroke-pen"
        strokeWidth={PEN_STROKE}
        style={{ scale: ringScale }}
      />
      <motion.circle
        cx={QUESTION_POINT.x}
        cy={QUESTION_POINT.y}
        r={QUESTION_RADIUS}
        className="fill-pen"
        style={{ scale }}
      />
    </>
  );
}

/** A pen line from the question to one of its two nearest passages. */
export function QuestionLink({
  to,
  citation,
  progress,
}: {
  to: Point;
  citation: Citation;
  progress: Progress;
}) {
  const delay = (citation - 1) * LINK_STAGGER;
  const [drawFrom, drawTo] = CUE.linkDraw;
  const [linkStart, linkEnd] = cue("question", [drawFrom + delay, drawTo + delay]);
  const pathLength = useTransform(progress, [linkStart, linkEnd], [0, 1]);
  const opacity = useTransform(progress, [linkStart, linkStart + LINK_APPEAR], [0, 1]);
  return (
    <motion.path
      d={`M${QUESTION_POINT.x} ${QUESTION_POINT.y}L${to.x} ${to.y}`}
      fill="none"
      className="stroke-pen"
      strokeWidth={PEN_STROKE}
      strokeLinecap="round"
      style={{ pathLength, opacity }}
    />
  );
}

/** The number that passage gets as a source, the same mark the answer uses. */
export function SourceBadge({
  citation,
  at,
  progress,
}: {
  citation: Citation;
  at: Point;
  progress: Progress;
}) {
  const [from, to] = cue("question", CUE.badgesAppear);
  // A function keeps this HTML element's opacity on the main thread. Given keyframes, motion
  // hands it to the browser's scroll timeline, which let the badge fade out again after `to`.
  const opacity = useTransform(progress, (value) => ramp(value, from, to));
  const offset = SOURCE_BADGE_OFFSET[citation];
  return (
    <motion.span
      aria-hidden
      className="absolute -translate-x-1/2 -translate-y-1/2"
      style={{
        left: `${((at.x + offset.x) / MAP_WIDTH) * 100}%`,
        top: `${((at.y + offset.y) / MAP_HEIGHT) * 100}%`,
        opacity,
      }}
    >
      <CitationMark number={citation} />
    </motion.span>
  );
}
