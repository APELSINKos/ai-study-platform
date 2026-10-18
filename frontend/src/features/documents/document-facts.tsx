"use client";

import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useId } from "react";

import { useMeta } from "@/features/meta/hooks";
import type { AiMode, Difficulty, DocumentOut } from "@/lib/api/types";
import { formatDuration } from "@/lib/format";

type FactsTranslator = ReturnType<typeof useTranslations<"Documents.facts">>;

const MINUTES_PER_HOUR = 60;
/** The built-in heuristic analyser names its models with this prefix. */
const BUILT_IN_MODEL_PREFIX = "mock-";

const DIFFICULTY_KEYS = {
  easy: "levels.easy",
  medium: "levels.medium",
  hard: "levels.hard",
} as const satisfies Record<Difficulty, string>;

interface Fact {
  term: string;
  value: string;
}

function studyTime(minutes: number, t: FactsTranslator): string {
  if (minutes < MINUTES_PER_HOUR) {
    return t("minutes", { minutes });
  }
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  const rest = minutes % MINUTES_PER_HOUR;
  return rest === 0 ? t("hours", { hours }) : t("hoursMinutes", { hours, minutes: rest });
}

/**
 * Who analysed the file. The built-in analyser is all there is offline; with a model configured
 * it stands in only for a file the model could not analyse.
 */
function analyser(model: string, mode: AiMode, t: FactsTranslator): string {
  if (!model.startsWith(BUILT_IN_MODEL_PREFIX)) {
    return model;
  }
  return mode === "offline" ? t("offlineAnalysis") : t("basicAnalysis");
}

/** What processing found out about a document, as ruled rows; facts not known yet are left out. */
export function DocumentFacts({
  document,
  className,
}: {
  document: DocumentOut;
  className?: string;
}) {
  const t = useTranslations("Documents.facts");
  const format = useFormatter();
  const locale = useLocale();
  const headingId = useId();
  const mode = useMeta().data?.ai.mode;

  const facts: Fact[] = [];
  if (document.difficulty !== null) {
    facts.push({ term: t("difficulty"), value: t(DIFFICULTY_KEYS[document.difficulty]) });
  }
  if (document.estimated_study_minutes !== null) {
    facts.push({ term: t("studyTime"), value: studyTime(document.estimated_study_minutes, t) });
  }
  if (document.page_count !== null) {
    facts.push({ term: t("pages"), value: format.number(document.page_count) });
  }
  if (document.word_count !== null) {
    facts.push({ term: t("words"), value: format.number(document.word_count) });
  }
  if (document.chunk_count !== null) {
    facts.push({ term: t("fragments"), value: format.number(document.chunk_count) });
  }
  if (document.processing_ms !== null) {
    facts.push({
      term: t("processingTime"),
      value: formatDuration(document.processing_ms, locale),
    });
  }
  // Without the AI mode a built-in model's name could not be told apart, so the row waits.
  if (document.analysis_model !== null && mode !== undefined) {
    facts.push({ term: t("analysis"), value: analyser(document.analysis_model, mode, t) });
  }

  if (facts.length === 0) {
    return null;
  }
  return (
    <section aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="font-display text-xl font-semibold">
        {t("title")}
      </h2>
      <dl className="border-rule divide-rule mt-4 divide-y border-y text-sm">
        {facts.map((fact) => (
          <div
            key={fact.term}
            className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-x-6 py-3 sm:grid-cols-[15rem_minmax(0,1fr)]"
          >
            <dt className="text-ink-soft">{fact.term}</dt>
            <dd className="text-ink break-words">{fact.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
