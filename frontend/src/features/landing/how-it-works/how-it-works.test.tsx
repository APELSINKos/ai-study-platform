import { screen, waitFor } from "@testing-library/react";
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
      "2Passages are mapped by meaning",
      "3Your question finds its neighbours",
      "4The answer cites them",
    ]);
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
      "The answer cites them",
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
