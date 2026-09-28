import { motion, useTransform } from "motion/react";
import { useId } from "react";

import { CUE, cue, type Progress } from "./map-cues";
import {
  CARD,
  CARD_SCALE_ON_MAP,
  GRID_STEP,
  HIGHLIGHT_BAND,
  MAP_HEIGHT,
  MAP_WIDTH,
  PAGE,
  PAGE_TITLE,
  PEN_STROKE,
  POINT_RADIUS,
  TEXT_BAR,
  type Passage,
  type Point,
} from "./map-geometry";
import { phaseWindow } from "./timeline";

/** Part of the track a point takes to grow in. */
const POINT_POP = 0.03;
/** Points that are not the question's neighbours fade back so the chosen two stand out. */
const DIMMED_OPACITY = 0.35;

/** The graph paper of the map, which appears as the passages settle on it. */
export function MapGrid({ progress }: { progress: Progress }) {
  const patternId = useId();
  const opacity = useTransform(progress, cue("map", CUE.gridAppears), [0, 1]);
  return (
    <motion.g style={{ opacity }}>
      <defs>
        <pattern id={patternId} width={GRID_STEP} height={GRID_STEP} patternUnits="userSpaceOnUse">
          <path d={`M${GRID_STEP} 0V${GRID_STEP}H0`} fill="none" className="stroke-rule" />
        </pattern>
      </defs>
      <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill={`url(#${patternId})`} />
    </motion.g>
  );
}

/** The printed page the story starts from; it fades once its passages become cards. */
export function PageSheet({ progress }: { progress: Progress }) {
  const opacity = useTransform(progress, cue("split", CUE.pageFades), [1, 0]);
  return (
    <motion.g style={{ opacity }}>
      <rect
        x={PAGE.x}
        y={PAGE.y}
        width={PAGE.width}
        height={PAGE.height}
        rx={PAGE.radius}
        className="fill-sheet stroke-rule-strong"
      />
      <rect
        x={PAGE_TITLE.x}
        y={PAGE_TITLE.y}
        width={PAGE_TITLE.width}
        height={PAGE_TITLE.height}
        rx={PAGE_TITLE.height / 2}
        className="fill-ink"
      />
    </motion.g>
  );
}

/** One passage: two lines on the page, then a card of its own that shrinks into its map point. */
export function PassageCard({ passage, progress }: { passage: Passage; progress: Progress }) {
  const [splitStart, splitEnd] = phaseWindow("split");
  const [mapStart, mapEnd] = phaseWindow("map");
  const journey = [splitStart, splitEnd, mapStart, mapEnd];
  const { onPage, card, onMap } = passage;

  const x = useTransform(progress, journey, [onPage.x, card.x, card.x, onMap.x]);
  const y = useTransform(progress, journey, [onPage.y, card.y, card.y, onMap.y]);
  const rotate = useTransform(progress, journey, [0, card.rotate, card.rotate, 0]);
  const scale = useTransform(progress, [mapStart, mapEnd], [1, CARD_SCALE_ON_MAP]);
  const opacity = useTransform(progress, cue("map", CUE.cardsFade), [1, 0]);
  const frameOpacity = useTransform(progress, cue("split", CUE.cardFramesAppear), [0, 1]);

  const [first, second] = passage.bars;

  return (
    <motion.g style={{ x, y, rotate, scale, opacity }}>
      <motion.rect
        x={-CARD.width / 2}
        y={-CARD.height / 2}
        width={CARD.width}
        height={CARD.height}
        rx={CARD.radius}
        className="fill-sheet stroke-rule-strong"
        style={{ opacity: frameOpacity }}
      />
      {passage.highlighted ? (
        <>
          <HighlightBand y={TEXT_BAR.firstY} width={first} />
          <HighlightBand y={TEXT_BAR.secondY} width={second} />
        </>
      ) : null}
      <TextBar y={TEXT_BAR.firstY} width={first} />
      <TextBar y={TEXT_BAR.secondY} width={second} />
    </motion.g>
  );
}

function HighlightBand({ y, width }: { y: number; width: number }) {
  const { padding, radius } = HIGHLIGHT_BAND;
  return (
    <rect
      x={TEXT_BAR.x - padding}
      y={y - padding}
      width={width + padding * 2}
      height={TEXT_BAR.height + padding * 2}
      rx={radius}
      className="fill-highlight"
    />
  );
}

function TextBar({ y, width }: { y: number; width: number }) {
  return (
    <rect
      x={TEXT_BAR.x}
      y={y}
      width={width}
      height={TEXT_BAR.height}
      rx={TEXT_BAR.height / 2}
      className="fill-ink-soft"
    />
  );
}

/** A passage on the map of meaning; the question's two neighbours stay dark when others fade. */
export function MapPoint({
  point,
  appearAt,
  progress,
  highlighted = false,
  isNeighbour = false,
}: {
  point: Point;
  appearAt: number;
  progress: Progress;
  highlighted?: boolean;
  isNeighbour?: boolean;
}) {
  const scale = useTransform(progress, [appearAt, appearAt + POINT_POP], [0, 1]);
  const opacity = useTransform(progress, cue("question", CUE.pointsDim), [
    1,
    isNeighbour ? 1 : DIMMED_OPACITY,
  ]);
  const fill = highlighted
    ? "fill-highlight stroke-ink"
    : isNeighbour
      ? "fill-ink"
      : "fill-ink-soft";
  return (
    <motion.circle
      cx={point.x}
      cy={point.y}
      r={POINT_RADIUS}
      className={fill}
      strokeWidth={highlighted ? PEN_STROKE : 0}
      style={{ scale, opacity }}
    />
  );
}
