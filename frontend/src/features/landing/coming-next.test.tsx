import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { stubIntersectionObserver } from "@/test/intersection-observer";
import { renderWithIntl } from "@/test/render";

import { ClosingCta } from "./closing-cta";
import { Hero } from "./hero/hero";
import { Practice } from "./practice/practice";
import { RememberLonger } from "./remember/remember-longer";

describe("the landing page's account of what Recall does", () => {
  beforeEach(() => {
    stubIntersectionObserver();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    ["Practise until it sticks", "en", "Coming next"],
    ["Remember it longer", "en", "Coming next"],
    ["Тренируйтесь, пока не запомнится", "ru", "Скоро"],
    ["Помните дольше", "ru", "Скоро"],
  ] as const)("marks the section “%s” as coming next (%s)", (title, locale: Locale, label) => {
    renderWithIntl(
      <>
        <Practice />
        <RememberLonger />
      </>,
      { locale },
    );

    const section = screen.getByRole("region", { name: title });
    const note = within(section).getByText(label);
    // Right under the section's title, before anything it says about the feature.
    expect(within(section).getByRole("heading", { level: 2 }).nextElementSibling).toBe(note);
  });

  it("speaks of quizzes, flashcards and reviews as features still to come", () => {
    renderWithIntl(
      <>
        <Practice />
        <RememberLonger />
      </>,
    );

    expect(screen.getByText(/Recall will write quizzes and flashcards/)).toBeInTheDocument();
    expect(screen.getByText(/Recall will schedule each card/)).toBeInTheDocument();
    expect(screen.getByText(/Quiz results will show/)).toBeInTheDocument();
  });

  it("tells what works today and what comes next from the first screen", () => {
    renderWithIntl(<Hero />);

    expect(screen.getByText(/cuts each file into passages/)).toHaveTextContent(
      "Answers with sources, quizzes and flashcards are coming next.",
    );
  });

  it("invites a first upload rather than a first question", () => {
    renderWithIntl(<ClosingCta />);

    expect(
      screen.getByText(
        "Create an account, upload the chapter you are studying now and see its summary, topics and study time.",
      ),
    ).toBeInTheDocument();
  });
});
