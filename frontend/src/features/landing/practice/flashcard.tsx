"use client";

import { motion } from "motion/react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

import { FLIP_SPRING, INSTANT } from "../motion";
import type { SampleCard } from "./sample-deck";

/** Ruled lines match the card text: 28px apart like `leading-7`, starting below `pt-1.5`. */
const RULE_SPACING = 28;
const TEXT_TOP = 6;
/** A 1px line centred half a pixel above the tile edge stays crisp. */
const RULE_Y = RULE_SPACING - 0.5;

/**
 * One index card of the demo deck. The whole card is a button: clicking it, or Space while it is
 * focused, turns it over in 3D. Only the face that is turned towards the reader is announced.
 */
export function Flashcard({
  card,
  counter,
  isFlipped,
  onFlip,
  describedBy,
  focusOnMount,
  reduceMotion,
}: {
  card: SampleCard;
  counter: string;
  isFlipped: boolean;
  onFlip: () => void;
  describedBy: string;
  focusOnMount: boolean;
  reduceMotion: boolean;
}) {
  const t = useTranslations("Landing.practice.cards");
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // A card dealt after a rating takes focus, so the keyboard stays in the demo.
    if (focusOnMount) {
      buttonRef.current?.focus();
    }
  }, [focusOnMount]);

  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onFlip}
      aria-describedby={describedBy}
      className="focus-visible:outline-pen absolute inset-0 block w-full cursor-pointer rounded-[0.25rem] text-left perspective-[1400px] focus-visible:outline-2 focus-visible:outline-offset-4"
    >
      <motion.span
        className="relative block size-full transform-3d"
        initial={false}
        animate={{ rotateY: isFlipped ? 180 : 0 }}
        transition={reduceMotion ? INSTANT : FLIP_SPRING}
      >
        <CardFace
          isHidden={isFlipped}
          header={t(`${card}.topic`)}
          aside={counter}
          text={t(`${card}.question`)}
          textClassName="text-[1.375rem] font-semibold"
        />
        <CardFace
          isBack
          isHidden={!isFlipped}
          header={t(`${card}.source`)}
          text={t(`${card}.answer`)}
          textClassName="text-lg"
        />
      </motion.span>
    </button>
  );
}

function CardFace({
  header,
  aside,
  text,
  textClassName,
  isHidden,
  isBack = false,
}: {
  header: string;
  aside?: ReactNode;
  text: string;
  textClassName: string;
  isHidden: boolean;
  isBack?: boolean;
}) {
  return (
    <span
      aria-hidden={isHidden}
      className={cn(
        "index-card absolute inset-0 flex flex-col overflow-hidden backface-hidden",
        isBack && "rotate-y-180",
      )}
    >
      <span className="text-ink-soft flex items-center justify-between gap-4 px-5 pt-3.5 pb-2.5 text-sm">
        <span>{header}</span>
        {aside ? <span className="tabular-nums">{aside}</span> : null}
      </span>
      <span className="relative flex-1 px-5 pt-1.5">
        <RuledLines />
        <span className={cn("font-display relative block leading-7", textClassName)}>{text}</span>
      </span>
    </span>
  );
}

function RuledLines() {
  const patternId = useId();
  return (
    <svg aria-hidden className="absolute inset-0 size-full">
      <defs>
        <pattern
          id={patternId}
          width={RULE_SPACING}
          height={RULE_SPACING}
          y={TEXT_TOP}
          patternUnits="userSpaceOnUse"
        >
          <line x1="0" x2={RULE_SPACING} y1={RULE_Y} y2={RULE_Y} className="stroke-rule" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${patternId})`} />
    </svg>
  );
}
