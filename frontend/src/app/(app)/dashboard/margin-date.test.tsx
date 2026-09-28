import { screen } from "@testing-library/react";
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
});
