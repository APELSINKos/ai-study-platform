import { screen, waitFor, within } from "@testing-library/react";
import type * as MotionModule from "motion/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { stubIntersectionObserver } from "@/test/intersection-observer";
import { renderWithIntl } from "@/test/render";

import { HowItWorks } from "./how-it-works";

const motionPreference = vi.hoisted(() => ({ reduce: false }));

vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof MotionModule>()),
  useReducedMotion: () => motionPreference.reduce,
}));

describe("HowItWorks", () => {
  beforeEach(() => {
    motionPreference.reduce = false;
    stubIntersectionObserver({ immediately: true });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists the four steps in order", () => {
    renderWithIntl(<HowItWorks />);

    expect(screen.getAllByRole("heading", { level: 3 }).map((step) => step.textContent)).toEqual([
      "1Your file becomes passages",
      "2Each passage gets a place on a map",
      "3Your question will find its neighbours",
      "4The answer will cite them",
    ]);
  });

  it.each([
    ["en", "Coming next"],
    ["ru", "Скоро"],
  ] as const)("marks the steps Recall does not take yet as coming next (%s)", (locale, label) => {
    renderWithIntl(<HowItWorks />, { locale });

    const marked = screen
      .getAllByRole("heading", { level: 3 })
      .map((title) => within(title.closest("li") as HTMLElement).queryByText(label) !== null);
    expect(marked).toEqual([false, false, true, true]);
  });

  it("does not claim that the built-in model maps passages by meaning", () => {
    renderWithIntl(<HowItWorks />);

    expect(screen.queryByText(/by meaning/i)).not.toBeInTheDocument();
    expect(screen.getByText(/use the same words/)).toBeInTheDocument();
  });

  it("starts the story at the first step with the answer not yet written", async () => {
    renderWithIntl(<HowItWorks />);

    await screen.findByTestId("meaning-map");
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent(
      "Your file becomes passages",
    );
    expect(screen.getByTestId("answer-card")).toHaveAttribute("data-shown", "false");
    expect(screen.getByTestId("answer-card")).toHaveAttribute("data-typed", "false");
  });

  it("shows the finished story at once when motion is reduced", async () => {
    motionPreference.reduce = true;
    renderWithIntl(<HowItWorks />);

    expect(await screen.findByTestId("meaning-map")).toHaveAttribute("data-static", "true");
    await waitFor(() =>
      expect(screen.getByTestId("answer-card")).toHaveAttribute("data-typed", "true"),
    );
    expect(screen.getByTestId("answer-card")).toHaveAttribute("data-shown", "true");
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent(
      "The answer will cite them",
    );
  });

  it("gives every claim of the answer a readable source mark", () => {
    renderWithIntl(<HowItWorks />);

    const card = screen.getByTestId("answer-card");
    expect(card).toHaveTextContent("How does reviewing slow down forgetting?");
    expect(card).toHaveTextContent(/within a day source 1/);
    expect(card).toHaveTextContent(/one sitting source 2/);
    expect(card).toHaveTextContent("Lecture 6, page 1");
  });
});
