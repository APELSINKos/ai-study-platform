import { screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/render";

import { daysUntilExam, ExamCountdown, parseExamDate } from "./exam-countdown";

// Local-time constructors: "today" is the browser's calendar day, whatever the runner's time zone.
describe("daysUntilExam", () => {
  it.each([
    ["2026-10-16", new Date(2026, 9, 16, 0, 0), 0],
    // Past midnight at UTC+3 it is still the 15th in UTC; the browser's day is what counts.
    ["2026-10-16", new Date(2026, 9, 16, 1, 30), 0],
    ["2026-10-16", new Date(2026, 9, 16, 23, 59), 0],
    ["2026-10-17", new Date(2026, 9, 16, 23, 59), 1],
    ["2026-10-28", new Date(2026, 9, 16, 9, 0), 12],
    ["2026-10-13", new Date(2026, 9, 16, 9, 0), -3],
    ["2027-01-02", new Date(2026, 11, 30, 18, 0), 3],
    ["2028-03-01", new Date(2028, 1, 28, 12, 0), 2],
    // Daylight saving time ends on 25 October 2026 in Europe; whole days stay whole.
    ["2026-10-27", new Date(2026, 9, 24, 12, 0), 3],
  ] as const)("counts %s from %s as %i days", (examDate, today, expected) => {
    expect(daysUntilExam(examDate, today)).toBe(expected);
  });

  it("is not a number for a date that does not exist", () => {
    expect(daysUntilExam("2026-02-30", new Date(2026, 1, 1))).toBeNaN();
  });
});

describe("parseExamDate", () => {
  it("reads a calendar date as midnight UTC", () => {
    expect(parseExamDate("2026-10-28")?.toISOString()).toBe("2026-10-28T00:00:00.000Z");
  });

  it.each([["2026-02-30"], ["2026-13-01"], ["28.10.2026"], ["2026-10-28T00:00:00Z"], [""]])(
    "rejects %j",
    (value) => {
      expect(parseExamDate(value)).toBeNull();
    },
  );
});

describe("ExamCountdown", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 16, 1, 30));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    ["2026-10-16", "Exam today"],
    ["2026-10-17", "Exam tomorrow"],
    ["2026-10-28", "Exam in 12 days"],
    ["2026-10-15", "Exam was yesterday"],
    ["2026-10-13", "Exam was 3 days ago"],
  ])("counts down to %s", (examDate, expected) => {
    renderWithIntl(<ExamCountdown examDate={examDate} />);

    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("names the exam day as a machine-readable date", () => {
    renderWithIntl(<ExamCountdown examDate="2026-10-28" />);

    const date = screen.getByText("October 28, 2026");
    expect(date.tagName).toBe("TIME");
    expect(date).toHaveAttribute("dateTime", "2026-10-28");
  });

  it("keeps the exam day whatever time zone the app is configured with", () => {
    // West of UTC, midnight UTC is still the evening before.
    renderWithIntl(
      <NextIntlClientProvider locale="en" timeZone="America/Los_Angeles">
        <ExamCountdown examDate="2026-10-28" />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("October 28, 2026")).toBeInTheDocument();
  });

  it.each([
    ["2026-10-18", "Экзамен через 2 дня"],
    ["2026-10-21", "Экзамен через 5 дней"],
    ["2026-10-27", "Экзамен через 11 дней"],
    ["2026-11-06", "Экзамен через 21 день"],
    ["2026-10-16", "Экзамен сегодня"],
    ["2026-10-17", "Экзамен завтра"],
    ["2026-10-15", "Экзамен был вчера"],
    ["2026-10-14", "Экзамен был 2 дня назад"],
    ["2026-10-11", "Экзамен был 5 дней назад"],
    ["2026-09-25", "Экзамен был 21 день назад"],
  ])("speaks Russian for %s", (examDate, expected) => {
    renderWithIntl(<ExamCountdown examDate={examDate} />, { locale: "ru" });

    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("names the exam day in Russian", () => {
    renderWithIntl(<ExamCountdown examDate="2026-10-28" />, { locale: "ru" });

    expect(screen.getByText("28 октября 2026 г.")).toBeInTheDocument();
  });

  it("renders nothing for a date that does not exist", () => {
    const { container } = renderWithIntl(<ExamCountdown examDate="2026-02-30" />);

    expect(container).toBeEmptyDOMElement();
  });
});
