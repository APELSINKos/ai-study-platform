"use client";

import { useFormatter, useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

const MS_PER_DAY = 86_400_000;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A `YYYY-MM-DD` calendar date as midnight UTC, or null when no such day exists. */
export function parseExamDate(value: string): Date | null {
  const match = ISO_DATE.exec(value);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month, day));
  // Date.UTC rolls an impossible day such as 30 February over into the next month.
  const exists =
    date.getUTCFullYear() === year && date.getUTCMonth() === month && date.getUTCDate() === day;
  return exists ? date : null;
}

/**
 * Whole days from the calendar day of `today` in the browser's time zone to the exam, negative
 * once it has passed. Both days are taken as midnight UTC, so a daylight saving change between
 * them cannot shift the count.
 */
export function daysUntilExam(examDate: string, today: Date): number {
  const exam = parseExamDate(examDate);
  if (!exam) {
    return Number.NaN;
  }
  const todayAtMidnight = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return (exam.getTime() - todayAtMidnight) / MS_PER_DAY;
}

export function ExamCountdown({ examDate, className }: { examDate: string; className?: string }) {
  const t = useTranslations("Workspaces.countdown");
  const format = useFormatter();
  const exam = parseExamDate(examDate);
  if (!exam) {
    return null;
  }
  const days = daysUntilExam(examDate, new Date());
  const isPast = days < 0;

  return (
    <p className={cn("flex flex-col gap-0.5 text-sm", className)}>
      <span className={isPast ? "text-ink-soft" : "text-ink font-medium"}>
        {isPast ? t("past", { days: -days }) : t("upcoming", { days })}
      </span>
      {/* The exam is a calendar day, not a moment: formatting it in UTC keeps that day. */}
      <time dateTime={examDate} className="text-ink-soft">
        {format.dateTime(exam, { timeZone: "UTC", dateStyle: "long" })}
      </time>
    </p>
  );
}
