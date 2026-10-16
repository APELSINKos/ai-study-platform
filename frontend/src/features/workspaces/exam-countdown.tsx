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

export interface ExamCountdownText {
  /** "Exam in 12 days", "Exam was yesterday" and the like. */
  countdown: string;
  /** The exam day in the reader's language. */
  date: string;
  /** The exam day as `YYYY-MM-DD`, for a `<time>` element. */
  dateTime: string;
  isPast: boolean;
}

/** The words for a countdown to `examDate`, or null without an exam day that exists. */
export function useExamCountdown(examDate: string | null): ExamCountdownText | null {
  const t = useTranslations("Workspaces.countdown");
  const format = useFormatter();
  const exam = examDate === null ? null : parseExamDate(examDate);
  if (examDate === null || exam === null) {
    return null;
  }
  const days = daysUntilExam(examDate, new Date());
  const isPast = days < 0;
  return {
    countdown: isPast ? t("past", { days: -days }) : t("upcoming", { days }),
    // The exam is a calendar day, not a moment: formatting it in UTC keeps that day.
    date: format.dateTime(exam, { timeZone: "UTC", dateStyle: "long" }),
    dateTime: examDate,
    isPast,
  };
}

export function ExamCountdown({ examDate, className }: { examDate: string; className?: string }) {
  const text = useExamCountdown(examDate);
  if (!text) {
    return null;
  }

  return (
    <p className={cn("flex flex-col gap-0.5 text-sm", className)}>
      <span className={text.isPast ? "text-ink-soft" : "text-ink font-medium"}>
        {text.countdown}
      </span>
      <time dateTime={text.dateTime} className="text-ink-soft">
        {text.date}
      </time>
    </p>
  );
}
