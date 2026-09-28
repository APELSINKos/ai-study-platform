/*
 * Layout of the "meaning map" illustration, in SVG user units. The same four passages are drawn
 * three times over the story: as lines on a page, as separate cards and as points on the map.
 */

export const MAP_WIDTH = 480;
export const MAP_HEIGHT = 360;

export interface Point {
  x: number;
  y: number;
}

export const PAGE = { x: 150, y: 34, width: 180, height: 252, radius: 4 } as const;
export const PAGE_TITLE = { x: 182, y: 56, width: 84, height: 7 } as const;

/** A passage card is drawn around its own centre so it can move and turn as one piece. */
export const CARD = { width: 148, height: 42, radius: 3 } as const;
export const TEXT_BAR = { x: -58, height: 5, firstY: -8, secondY: 4 } as const;
/** How small a card gets as it settles into a point on the map. */
export const CARD_SCALE_ON_MAP = 0.12;

export const POINT_RADIUS = 5;
/** Width of pen lines: the question ring, its links and the outline of the highlighted point. */
export const PEN_STROKE = 1.5;
export const HIGHLIGHT_BAND = { padding: 4, radius: 2 } as const;
export const QUESTION_RADIUS = 6;
export const QUESTION_RING_RADIUS = 13;
export const GRID_STEP = 24;

export type Citation = 1 | 2;

/** Where each source badge sits relative to its point: below-left and below-right. */
export const SOURCE_BADGE_OFFSET: Record<Citation, Point> = {
  1: { x: -16, y: 18 },
  2: { x: 18, y: 18 },
};

export interface Passage {
  id: string;
  /** Widths of the two lines of text on the card. */
  bars: readonly [number, number];
  onPage: Point;
  card: Point & { rotate: number };
  onMap: Point;
  /** The lines the student highlighted on the hero page. */
  highlighted: boolean;
  /** Set for the passages nearest to the question; they become the answer's sources. */
  citation?: Citation;
}

export const PASSAGES: readonly Passage[] = [
  {
    id: "history",
    bars: [112, 86],
    onPage: { x: 240, y: 98 },
    card: { x: 126, y: 98, rotate: -3 },
    onMap: { x: 118, y: 150 },
    highlighted: false,
  },
  {
    id: "forgetting",
    bars: [116, 70],
    onPage: { x: 240, y: 144 },
    card: { x: 354, y: 104, rotate: 2 },
    onMap: { x: 296, y: 128 },
    highlighted: true,
    citation: 1,
  },
  {
    id: "spacing",
    bars: [108, 94],
    onPage: { x: 240, y: 190 },
    card: { x: 132, y: 254, rotate: 2.5 },
    onMap: { x: 372, y: 130 },
    highlighted: false,
    citation: 2,
  },
  {
    id: "method",
    bars: [114, 60],
    onPage: { x: 240, y: 236 },
    card: { x: 350, y: 250, rotate: -2 },
    onMap: { x: 236, y: 272 },
    highlighted: false,
  },
];

/** Passages from the reader's other files, already on the map in small clusters. */
export const OTHER_POINTS: readonly Point[] = [
  { x: 92, y: 116 },
  { x: 150, y: 110 },
  { x: 82, y: 180 },
  { x: 144, y: 198 },
  { x: 338, y: 176 },
  { x: 404, y: 182 },
  { x: 204, y: 304 },
  { x: 272, y: 306 },
  { x: 210, y: 246 },
  { x: 318, y: 322 },
  { x: 196, y: 66 },
  { x: 426, y: 272 },
];

export const QUESTION_POINT: Point = { x: 332, y: 86 };
