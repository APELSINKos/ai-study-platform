import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/render";

import { CitationPopover } from "./citation-popover";
import { citationFixture } from "./test-fixtures";

describe("CitationPopover", () => {
  it("opens on keyboard activation, shows quote and passage link, and closes on Escape", async () => {
    const citation = citationFixture(1, {
      document_id: "00000000-0000-4000-9000-000000000042",
      document_title: "Lecture 6",
      chunk_index: 5,
      heading: "Lecture 6 › Spaced repetition",
      page_start: 4,
      page_end: 5,
      quote: "Each review makes the next loss slower.",
    });

    renderWithIntl(<CitationPopover citation={citation} />);

    const trigger = screen.getByRole("button", { name: "Source 1: Lecture 6" });
    expect(trigger).toHaveClass("size-6");
    trigger.focus();
    await userEvent.keyboard("{Enter}");

    const dialog = await screen.findByRole("dialog", { name: "Source 1: Lecture 6" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Each review makes the next loss slower.")).toBeInTheDocument();
    expect(screen.getByText("Spaced repetition")).toBeInTheDocument();
    expect(screen.getByText("Pages 4–5")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("·");

    const openLink = screen.getByRole("link", { name: "Open passage" });
    expect(openLink).toHaveAttribute(
      "href",
      "/documents/00000000-0000-4000-9000-000000000042?fragment=5",
    );

    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByText("Each review makes the next loss slower.")).not.toBeInTheDocument(),
    );
    expect(trigger).toHaveFocus();
  });

  it("closes via the explicit Close button and renders untrusted text safely", async () => {
    const markup = "<img src=x onerror=alert(1)>";
    const citation = citationFixture(2, {
      document_title: `${markup} title`,
      heading: `${markup} section`,
      page_start: null,
      page_end: null,
      quote: `${markup} quote`,
    });

    renderWithIntl(<CitationPopover citation={citation} variant="source" />);

    await userEvent.click(screen.getByRole("button", { name: `Source 2: ${markup} title` }));
    expect(await screen.findByText(`${markup} quote`)).toBeInTheDocument();
    expect(screen.getByText(`${markup} section`)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Close source preview" }));
    await waitFor(() => expect(screen.queryByText(`${markup} quote`)).not.toBeInTheDocument());
  });

  it("speaks Russian", async () => {
    const citation = citationFixture(1, {
      document_title: "Лекция 6",
      heading: "Лекция 6",
      page_start: 3,
      page_end: 3,
      quote: "Каждое повторение замедляет забывание.",
    });

    renderWithIntl(<CitationPopover citation={citation} />, { locale: "ru" });

    await userEvent.click(screen.getByRole("button", { name: "Источник 1: Лекция 6" }));

    expect(await screen.findByRole("dialog", { name: "Источник 1: Лекция 6" })).toBeInTheDocument();
    expect(screen.getByText("Каждое повторение замедляет забывание.")).toBeInTheDocument();
    expect(screen.getByText("Страница 3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть фрагмент" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Закрыть фрагмент" })).toBeInTheDocument();
  });
});
