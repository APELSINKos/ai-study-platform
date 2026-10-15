import { screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/render";

import { DashboardMarginDate } from "./margin-date";

describe("DashboardMarginDate", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-28T10:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows today's date in English after mount", () => {
    renderWithIntl(<DashboardMarginDate />);

    expect(screen.getByText("Monday, September 28")).toBeInTheDocument();
  });

  it("shows today's date in Russian after mount", () => {
    renderWithIntl(<DashboardMarginDate />, { locale: "ru" });

    expect(screen.getByText("понедельник, 28 сентября")).toBeInTheDocument();
  });

  // The app inherits the server's time zone, which is not the reader's. Local-time constructors
  // put "now" at the edges of the browser's day, wherever the test runs.
  it.each([
    ["Pacific/Kiritimati", new Date(2026, 8, 28, 23, 30)],
    ["Etc/GMT+12", new Date(2026, 8, 28, 0, 30)],
  ])("shows the browser's calendar day when the app's time zone is %s", (timeZone, now) => {
    vi.setSystemTime(now);

    renderWithIntl(
      <NextIntlClientProvider locale="en" timeZone={timeZone}>
        <DashboardMarginDate />
      </NextIntlClientProvider>,
    );

    expect(screen.getByText("Monday, September 28")).toBeInTheDocument();
  });
});
