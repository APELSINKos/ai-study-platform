"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useTranslations } from "next-intl";
import { useId, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { DURATION, INSTANT, PEN_EASE } from "../motion";
import { Flashcard } from "./flashcard";
import {
  RATINGS,
  SAMPLE_CARDS,
  cardAt,
  nextPosition,
  ratingForKey,
  type Rating,
} from "./sample-deck";

/** How a rated card leaves: slid off to the left with a slight turn, like a hand dealing. */
const DEALT_AWAY = { opacity: 0, x: -48, rotate: -5 };
const DEALT_IN = { opacity: 0, y: 12, scale: 0.97 };
const IN_PLACE = { opacity: 1, x: 0, y: 0, rotate: 0, scale: 1 };

/** Controls hidden until they apply keep their space, so nothing below them moves. */
const CONCEALED = "invisible opacity-0";

/**
 * A small illustration of reviewing flashcards: flip the card, rate how well you remembered it,
 * see when it would come back, and get the next card. Number keys 1 to 4 rate a flipped card.
 */
export function FlashcardDemo() {
  const t = useTranslations("Landing.practice");
  const reduceMotion = useReducedMotion() ?? false;
  const hintId = useId();
  const [position, setPosition] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);
  const [lastRating, setLastRating] = useState<Rating | null>(null);

  const card = cardAt(position);

  function rate(rating: Rating) {
    setLastRating(rating);
    setIsFlipped(false);
    setPosition(nextPosition);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!isFlipped || event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }
    const rating = ratingForKey(event.key);
    if (rating) {
      event.preventDefault();
      rate(rating);
    }
  }

  return (
    <div role="group" aria-label={t("demoLabel")} onKeyDown={handleKeyDown} className="w-full">
      <div className="relative h-64 sm:h-72">
        <span
          aria-hidden
          className="index-card absolute inset-0 translate-x-2.5 translate-y-3 rotate-[2.5deg]"
        />
        <span
          aria-hidden
          className="index-card absolute inset-0 translate-x-1 translate-y-1.5 -rotate-[1.25deg]"
        />
        <AnimatePresence initial={false}>
          <motion.div
            key={position}
            className="absolute inset-0"
            initial={reduceMotion ? false : DEALT_IN}
            animate={IN_PLACE}
            exit={reduceMotion ? { opacity: 0, transition: INSTANT } : DEALT_AWAY}
            transition={{ duration: DURATION.deal, ease: PEN_EASE }}
          >
            <Flashcard
              card={card}
              counter={t("counter", { current: position + 1, total: SAMPLE_CARDS.length })}
              isFlipped={isFlipped}
              onFlip={() => setIsFlipped((flipped) => !flipped)}
              describedBy={hintId}
              focusOnMount={lastRating !== null}
              reduceMotion={reduceMotion}
            />
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Written under the deck like a pen note: when the card just rated comes back. */}
      <p
        role="status"
        className="font-display text-pen mt-5 min-h-7 text-[0.9375rem] leading-7 italic"
      >
        {lastRating ? t("scheduled", { interval: t(`ratings.${lastRating}.interval`) }) : null}
      </p>

      <div className="mt-2 grid h-24">
        <p
          id={hintId}
          className={cn(
            "text-ink-soft text-sm leading-6 transition-[opacity,visibility] duration-200 [grid-area:1/1]",
            isFlipped && CONCEALED,
          )}
        >
          {t("hint")}
        </p>
        <div
          role="group"
          aria-labelledby={`${hintId}-rate`}
          className={cn(
            "transition-[opacity,visibility] duration-200 [grid-area:1/1]",
            !isFlipped && CONCEALED,
          )}
        >
          <p id={`${hintId}-rate`} className="text-ink-soft text-sm leading-6">
            {t("rateLabel")}
          </p>
          <div className="mt-2 grid grid-cols-4 gap-2">
            {RATINGS.map((rating, index) => (
              <Button
                key={rating}
                variant="secondary"
                aria-keyshortcuts={String(index + 1)}
                className="h-auto flex-col gap-0.5 px-1 py-2"
                onClick={() => rate(rating)}
              >
                <span>{t(`ratings.${rating}.label`)}</span>
                <span className="text-ink-soft text-xs font-normal">
                  {t(`ratings.${rating}.interval`)}
                </span>
              </Button>
            ))}
          </div>
        </div>
      </div>

      <p aria-live="polite" className="sr-only">
        {isFlipped ? t("flipped", { answer: t(`cards.${card}.answer`) }) : null}
      </p>
    </div>
  );
}
