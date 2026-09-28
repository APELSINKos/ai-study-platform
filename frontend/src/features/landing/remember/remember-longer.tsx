import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import { LazyMount } from "../lazy-mount";
import { CHART_HEIGHT, CHART_WIDTH, xOf } from "./curve";
import { ForgettingCurve } from "./forgetting-curve";

const DAYS_IN_WEEK = 7;
/** On phone widths "1 week" would touch "Lecture", so that tick is only shown from `sm` up. */
const AXIS_TICKS = [
  { key: "start", day: 0, className: "" },
  { key: "week", day: DAYS_IN_WEEK, className: "max-sm:hidden" },
  { key: "twoWeeks", day: 2 * DAYS_IN_WEEK, className: "" },
  { key: "fourWeeks", day: 4 * DAYS_IN_WEEK, className: "" },
] as const;

export function RememberLonger() {
  const t = useTranslations("Landing.remember");

  return (
    <section aria-labelledby="remember-title" className="notebook-row mt-32 sm:mt-44">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <h2 id="remember-title" className="font-display text-headline font-semibold text-balance">
          {t("title")}
        </h2>
        <div className="text-ink-soft max-w-[56ch] space-y-4 text-lg leading-8">
          <p>{t("body")}</p>
          <p>{t("weakTopics")}</p>
        </div>
      </div>
      <p className="margin-note mt-12 md:mt-16">{t("note")}</p>
      <figure className="max-w-3xl md:mt-16">
        {/* The caption below describes the chart, so its drawing and labels are not read out. */}
        <div aria-hidden>
          <div className="text-ink-soft flex flex-wrap items-center justify-between gap-x-8 gap-y-2 text-sm">
            <span>{t("yAxis")}</span>
            <span className="flex flex-wrap gap-x-6 gap-y-2">
              <LegendKey dashed label={t("withoutReview")} />
              <LegendKey label={t("withReviews")} />
            </span>
          </div>
          <div
            className="relative mt-5"
            style={{ aspectRatio: `${CHART_WIDTH} / ${CHART_HEIGHT}` }}
          >
            <LazyMount className="absolute inset-0">
              <ForgettingCurve />
            </LazyMount>
          </div>
          <div className="text-ink-soft relative mt-3 h-5 text-xs">
            {AXIS_TICKS.map(({ key, day, className }) => (
              <span
                key={key}
                className={cn(
                  "absolute top-0 whitespace-nowrap",
                  day === 0 ? "" : "-translate-x-1/2",
                  className,
                )}
                style={{ left: `${(xOf(day) / CHART_WIDTH) * 100}%` }}
              >
                {t(`axis.${key}`)}
              </span>
            ))}
          </div>
        </div>
        <figcaption className="text-ink-soft mt-8 max-w-[62ch] text-sm leading-6">
          {t("caption")}
        </figcaption>
      </figure>
    </section>
  );
}

function LegendKey({ label, dashed = false }: { label: string; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <svg aria-hidden viewBox="0 0 24 4" className="h-1 w-6 overflow-visible">
        <line
          x1="0"
          x2="24"
          y1="2"
          y2="2"
          strokeWidth={dashed ? 2 : 2.5}
          strokeDasharray={dashed ? "4 4" : undefined}
          className={dashed ? "stroke-ink-soft" : "stroke-pen"}
        />
      </svg>
      {label}
    </span>
  );
}
