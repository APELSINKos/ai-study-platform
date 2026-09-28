import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type * as MotionModule from "motion/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/render";

import { FlashcardDemo } from "./flashcard-demo";

const motionPreference = vi.hoisted(() => ({ reduce: false }));

vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof MotionModule>()),
  useReducedMotion: () => motionPreference.reduce,
}));

const FIRST_QUESTION = /What did Ebbinghaus measure in 1885\?/;
const FIRST_ANSWER = /He measured how much of a memorised list he could still recall/;
const SECOND_QUESTION = /Why do spaced reviews beat rereading in one sitting\?/;

function renderDemo() {
  const user = userEvent.setup();
  renderWithIntl(<FlashcardDemo />);
  return { user, card: screen.getByRole("button", { name: FIRST_QUESTION }) };
}

describe("FlashcardDemo", () => {
  beforeEach(() => {
    motionPreference.reduce = false;
  });

  it("turns the card over when it is clicked", async () => {
    const { user, card } = renderDemo();

    await user.click(card);

    expect(card).toHaveAccessibleName(FIRST_ANSWER);
    expect(screen.getByText(/^Answer: He measured how much/)).toBeInTheDocument();
  });

  it("turns the card over with Space and back again", async () => {
    const { user, card } = renderDemo();

    card.focus();
    await user.keyboard(" ");
    expect(card).toHaveAccessibleName(FIRST_ANSWER);

    await user.keyboard(" ");
    expect(card).toHaveAccessibleName(FIRST_QUESTION);
  });

  it("deals the next card after a rating and says when the rated one comes back", async () => {
    const { user, card } = renderDemo();

    await user.click(card);
    const ratings = screen.getByRole("group", { name: "How well did you remember?" });
    await user.click(within(ratings).getByRole("button", { name: "Good 3 days" }));

    expect(screen.getByRole("status")).toHaveTextContent("Next review in 3 days.");
    const next = await screen.findByRole("button", { name: SECOND_QUESTION });
    expect(next).toHaveAccessibleName(/2 of 4/);
    // The keyboard stays in the demo: the new card can be flipped with Space right away.
    expect(next).toHaveFocus();
  });

  it("rates a flipped card with the number keys", async () => {
    const { user, card } = renderDemo();

    // A card that has not been turned over yet cannot be rated.
    card.focus();
    await user.keyboard("4");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();

    await user.keyboard(" ");
    await user.keyboard("4");

    expect(screen.getByRole("status")).toHaveTextContent("Next review in 5 days.");
  });

  it("shows every example interval on the rating buttons", () => {
    renderDemo();

    const ratings = screen.getByRole("group", { name: "How well did you remember?" });
    expect(
      within(ratings)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Again10 min", "Hard1 day", "Good3 days", "Easy5 days"]);
  });

  it("deals the next card in place, without movement, when motion is reduced", async () => {
    motionPreference.reduce = true;
    const { user, card } = renderDemo();

    await user.click(card);
    await user.click(screen.getByRole("button", { name: "Easy 5 days" }));

    const next = await screen.findByRole("button", { name: SECOND_QUESTION });
    // Without reduced motion a dealt card starts lower, smaller and transparent.
    const wrapper = next.parentElement;
    expect(["", "none"]).toContain(wrapper?.style.transform);
    expect(wrapper?.style.opacity).not.toBe("0");
  });

  it("speaks Russian when the interface does", async () => {
    const user = userEvent.setup();
    renderWithIntl(<FlashcardDemo />, { locale: "ru" });

    await user.click(screen.getByRole("button", { name: /Что измерял Эббингауз/ }));
    await user.click(screen.getByRole("button", { name: "Хорошо 3 дня" }));

    expect(screen.getByRole("status")).toHaveTextContent("Следующее повторение через 3 дня.");
  });
});
