"use client";

import { motion, useReducedMotion, type Transition } from "motion/react";

import type { DocumentStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { DOCUMENT_STAGES } from "./status";

// The view box matches the drawn size, so every number below is in CSS pixels.
const INSET = 4;
const STAGE_SPACING = 20;
const LAST_STAGE = DOCUMENT_STAGES.length - 1;
const WIDTH = INSET * 2 + STAGE_SPACING * LAST_STAGE;
const HEIGHT = 16;
const RAIL_Y = 8;
const DOT_RADIUS = 3;
const OPEN_DOT_RADIUS = 2.5;
const HALO_RADIUS = 5.5;
const RUNNER_RADIUS = 2;
/** How far the failure branch runs along the rail before it bends away. */
const BRANCH_PULL = 6;
/** A failed document drops off the rail just before the stage it never finished. */
const FAILURE_X = INSET + STAGE_SPACING - BRANCH_PULL;
const FAILURE_Y = HEIGHT - DOT_RADIUS;

const RUN: Transition = { duration: 1.4, ease: "easeInOut", repeat: Infinity, repeatDelay: 0.4 };
const RUN_FADE: Transition = { ...RUN, ease: "linear", times: [0, 0.2, 0.7, 1] };

type StageState = "passed" | "current" | "ahead" | "skipped";

const STAGE_DOT_CLASSES: Record<StageState, string> = {
  passed: "fill-pen",
  current: "fill-pen",
  ahead: "fill-sheet stroke-rule-strong",
  skipped: "fill-sheet stroke-rule-strong",
};

function stageX(index: number): number {
  return INSET + index * STAGE_SPACING;
}

function stageState(status: DocumentStatus, index: number): StageState {
  if (status === "failed") {
    return index === 0 ? "passed" : "skipped";
  }
  const reached = DOCUMENT_STAGES.indexOf(status);
  if (index < reached || status === "ready") {
    return "passed";
  }
  return index === reached ? "current" : "ahead";
}

interface StatusRailProps {
  status: DocumentStatus;
  /** Whether the document is moving on: a dot then runs towards the next stage. */
  moving: boolean;
  className?: string;
}

/**
 * The stages of processing as stations on a ruled line: uploaded, processing, indexing, ready.
 * A picture only, hidden from assistive technology; the stage is always told in words beside it.
 */
export function StatusRail({ status, moving, className }: StatusRailProps) {
  const reduceMotion = useReducedMotion() ?? false;
  const isFailed = status === "failed";
  const isReady = status === "ready";
  const reached = isFailed ? 0 : DOCUMENT_STAGES.indexOf(status);

  return (
    <svg
      aria-hidden
      focusable="false"
      width={WIDTH}
      height={HEIGHT}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className={cn("shrink-0 overflow-visible", className)}
    >
      <line
        x1={stageX(0)}
        x2={stageX(LAST_STAGE)}
        y1={RAIL_Y}
        y2={RAIL_Y}
        strokeWidth={1}
        strokeDasharray={isFailed ? "2 3" : undefined}
        className="stroke-rule-strong"
      />
      {reached > 0 ? (
        <line
          x1={stageX(0)}
          x2={stageX(reached)}
          y1={RAIL_Y}
          y2={RAIL_Y}
          strokeWidth={1.5}
          className={isReady ? "stroke-ok" : "stroke-pen"}
        />
      ) : null}
      {isFailed ? (
        <>
          <path
            d={`M${stageX(0)} ${RAIL_Y} C${stageX(0) + BRANCH_PULL} ${RAIL_Y} ${FAILURE_X - BRANCH_PULL} ${FAILURE_Y} ${FAILURE_X} ${FAILURE_Y}`}
            strokeWidth={1.5}
            className="stroke-margin fill-none"
          />
          <circle
            data-failure
            cx={FAILURE_X}
            cy={FAILURE_Y}
            r={DOT_RADIUS}
            className="fill-margin"
          />
        </>
      ) : null}
      {!isFailed && !isReady ? (
        <circle cx={stageX(reached)} cy={RAIL_Y} r={HALO_RADIUS} className="fill-pen/15" />
      ) : null}
      {DOCUMENT_STAGES.map((stage, index) => {
        const state = stageState(status, index);
        const isOpen = state === "ahead" || state === "skipped";
        return (
          <circle
            key={stage}
            data-stage={stage}
            data-state={state}
            cx={stageX(index)}
            cy={RAIL_Y}
            r={isOpen ? OPEN_DOT_RADIUS : DOT_RADIUS}
            strokeWidth={isOpen ? 1 : undefined}
            className={isReady ? "fill-ok" : STAGE_DOT_CLASSES[state]}
          />
        );
      })}
      {moving && !isFailed && !isReady ? (
        <Runner from={stageX(reached)} reduceMotion={reduceMotion} />
      ) : null}
    </svg>
  );
}

/** The dot that runs from the current stage to the next; with reduced motion it rests between them. */
function Runner({ from, reduceMotion }: { from: number; reduceMotion: boolean }) {
  if (reduceMotion) {
    return (
      <circle
        data-running="still"
        cx={from + STAGE_SPACING / 2}
        cy={RAIL_Y}
        r={RUNNER_RADIUS}
        className="fill-pen"
      />
    );
  }
  return (
    <motion.circle
      data-running="animated"
      cx={from}
      cy={RAIL_Y}
      r={RUNNER_RADIUS}
      className="fill-pen"
      initial={{ x: 0, opacity: 0 }}
      animate={{ x: STAGE_SPACING, opacity: [0, 1, 1, 0] }}
      transition={{ x: RUN, opacity: RUN_FADE }}
    />
  );
}
