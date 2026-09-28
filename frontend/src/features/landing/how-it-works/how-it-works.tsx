"use client";

import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import { LazyMount } from "../lazy-mount";
import { AnswerCard } from "./answer-card";
import { MeaningMap } from "./meaning-map";
import { StepList } from "./step-list";
import { hasReached, stepOf, type Phase } from "./timeline";

/**
 * "How it works": a tall track whose content stays pinned while the reader scrolls through it,
 * so scrolling plays the story from a marked page to a cited answer. Without motion the track
 * collapses to its content and everything is shown finished.
 */
export function HowItWorks() {
  const t = useTranslations("Landing.how");
  const trackRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>("page");

  return (
    <section aria-labelledby="how-title" className="notebook-row mt-32 sm:mt-44">
      <div>
        <h2 id="how-title" className="font-display text-headline font-semibold text-balance">
          {t("title")}
        </h2>
        <p className="text-ink-soft mt-4 max-w-[52ch] text-lg leading-8">{t("lead")}</p>
      </div>
      <div ref={trackRef} className="motion-safe:h-[360vh]">
        <div className="top-0 flex items-center py-6 motion-safe:sticky motion-safe:min-h-svh lg:py-12">
          <div className="grid w-full gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-center lg:gap-16">
            <StepList active={stepOf(phase)} />
            <div className="grid gap-4">
              <div className="rounded-panel border-rule bg-paper relative aspect-[4/3] overflow-hidden border">
                <LazyMount className="absolute inset-0">
                  <MeaningMap trackRef={trackRef} onPhaseChange={setPhase} />
                </LazyMount>
              </div>
              <AnswerCard
                isShown={hasReached(phase, "question")}
                isTyped={hasReached(phase, "answer")}
              />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
