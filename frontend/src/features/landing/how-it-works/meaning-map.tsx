"use client";

import { useMotionValue, useMotionValueEvent, useReducedMotion, useScroll } from "motion/react";
import { useEffect, type RefObject } from "react";

import { MAP_HEIGHT, MAP_WIDTH, OTHER_POINTS, PASSAGES } from "./map-geometry";
import { MapGrid, MapPoint, PageSheet, PassageCard } from "./map-passages";
import { QuestionLink, QuestionPoint, SourceBadge } from "./map-question";
import { FINAL_PHASE, phaseAt, within, type Phase } from "./timeline";

/** Other passages pop onto the map one after another during the map phase. */
const OTHER_POINTS_FROM = 0.1;
const OTHER_POINTS_STAGGER = 0.05;
/** The four passages of the page land as points once their cards have almost faded. */
const PASSAGE_POINTS_AT = 0.75;

/**
 * The pinned illustration of "How it works": a page splits into passage cards, the cards settle
 * as points on a map of meaning, a question lands among them and its nearest passages connect.
 * Scroll drives every value; with reduced motion the map is drawn in its finished state.
 */
export function MeaningMap({
  trackRef,
  onPhaseChange,
}: {
  trackRef: RefObject<HTMLElement | null>;
  onPhaseChange: (phase: Phase) => void;
}) {
  const reduceMotion = useReducedMotion() ?? false;
  const { scrollYProgress } = useScroll({ target: trackRef, offset: ["start start", "end end"] });
  const finished = useMotionValue(1);
  const progress = reduceMotion ? finished : scrollYProgress;

  useEffect(() => {
    onPhaseChange(reduceMotion ? FINAL_PHASE : phaseAt(scrollYProgress.get()));
  }, [reduceMotion, scrollYProgress, onPhaseChange]);

  useMotionValueEvent(scrollYProgress, "change", (value) => {
    if (!reduceMotion) {
      onPhaseChange(phaseAt(value));
    }
  });

  return (
    <div data-testid="meaning-map" data-static={reduceMotion || undefined} className="size-full">
      <svg
        aria-hidden
        viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
        className="absolute inset-0 size-full"
      >
        <MapGrid progress={progress} />
        <PageSheet progress={progress} />
        {OTHER_POINTS.map((point, index) => (
          <MapPoint
            key={`${point.x}-${point.y}`}
            point={point}
            appearAt={within("map", OTHER_POINTS_FROM + index * OTHER_POINTS_STAGGER)}
            progress={progress}
          />
        ))}
        {PASSAGES.map((passage) =>
          passage.citation ? (
            <QuestionLink
              key={passage.id}
              to={passage.onMap}
              citation={passage.citation}
              progress={progress}
            />
          ) : null,
        )}
        {PASSAGES.map((passage) => (
          <MapPoint
            key={passage.id}
            point={passage.onMap}
            appearAt={within("map", PASSAGE_POINTS_AT)}
            highlighted={passage.highlighted}
            isNeighbour={passage.citation !== undefined}
            progress={progress}
          />
        ))}
        {PASSAGES.map((passage) => (
          <PassageCard key={passage.id} passage={passage} progress={progress} />
        ))}
        <QuestionPoint progress={progress} />
      </svg>
      {PASSAGES.map((passage) =>
        passage.citation ? (
          <SourceBadge
            key={passage.id}
            citation={passage.citation}
            at={passage.onMap}
            progress={progress}
          />
        ) : null,
      )}
    </div>
  );
}
