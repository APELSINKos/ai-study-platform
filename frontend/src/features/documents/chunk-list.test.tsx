import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { ChunkList } from "./chunk-list";
import {
  chunkFixture,
  chunkPageFixture,
  documentFixture,
  readyDocumentFixture,
} from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const READY = readyDocumentFixture(1);
const FIRST_PAGE_PATH = `/documents/${READY.id}/chunks?page=1&page_size=50`;
const SECOND_PAGE_PATH = `/documents/${READY.id}/chunks?page=2&page_size=50`;
const FIRST_FIFTY = Array.from({ length: 50 }, (_, index) => chunkFixture(index));

function renderList(document: DocumentOut = READY, locale: Locale = "en") {
  return renderWithIntl(<ChunkList document={document} />, { locale });
}

function region(name = "Fragments"): HTMLElement {
  return screen.getByRole("region", { name });
}

function rows(): HTMLElement[] {
  return within(region()).getAllByRole("listitem");
}

describe("ChunkList", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it.each([
    ["uploaded", documentFixture(1, { status: "uploaded" })],
    ["indexing", documentFixture(1, { status: "indexing" })],
  ])("says the fragments come once the file is processed while it is %s", (_, document) => {
    apiFetchMock.mockResolvedValue(chunkPageFixture([chunkFixture(0)]));
    renderList(document);

    expect(
      within(region()).getByText("Fragments appear once the file is processed."),
    ).toBeInTheDocument();
    expect(within(region()).queryByRole("list")).not.toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("says a failed document has no fragments instead of promising them", () => {
    apiFetchMock.mockResolvedValue(chunkPageFixture([chunkFixture(0)]));
    renderList(documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true }));

    expect(
      within(region()).getByText("There are no fragments because the file could not be processed."),
    ).toBeInTheDocument();
    expect(
      within(region()).queryByText("Fragments appear once the file is processed."),
    ).not.toBeInTheDocument();
    expect(within(region()).queryByRole("list")).not.toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("shows that the fragments are loading", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderList();

    expect(within(region()).getByText("Loading fragments…")).toBeInTheDocument();
    expect(region().querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("lists the fragments in reading order, each with its headings and pages", async () => {
    apiFetchMock.mockResolvedValue(
      chunkPageFixture([
        chunkFixture(0, { heading: "Normal forms › First normal form", page_end: 2 }),
        chunkFixture(1, { heading: null, page_start: 3, page_end: 3 }),
      ]),
    );
    renderList();

    await within(region()).findByText("Passage 1 of the lecture.");
    expect(apiFetchMock).toHaveBeenCalledWith(FIRST_PAGE_PATH);
    const [first, second] = rows();
    expect(first).toHaveTextContent("Normal forms › First normal form");
    expect(first).toHaveTextContent("Pages 1–2");
    expect(first).toHaveTextContent("Passage 0 of the lecture.");
    expect(second).toHaveTextContent("Page 3");
    expect(second).toHaveTextContent("Passage 1 of the lecture.");
    expect(within(region()).getByRole("list").tagName).toBe("OL");
  });

  it("keeps the line breaks of a fragment's text", async () => {
    apiFetchMock.mockResolvedValue(
      chunkPageFixture([chunkFixture(0, { content: "First line\nSecond line" })]),
    );
    renderList();

    const text = await within(region()).findByText(/First line/);
    expect(text.textContent).toBe("First line\nSecond line");
    expect(text).toHaveClass("whitespace-pre-wrap");
  });

  it("shows only the text of a fragment that has neither headings nor pages", async () => {
    apiFetchMock.mockResolvedValue(
      chunkPageFixture([
        chunkFixture(0, { content: "Plain notes.", page_start: null, page_end: null }),
      ]),
    );
    renderList({ ...READY, content_type: "text/plain", page_count: null });

    await within(region()).findByText("Plain notes.");
    const [row] = rows();
    expect(row?.querySelectorAll("p")).toHaveLength(1);
    expect(row).not.toHaveTextContent(/Page/);
  });

  it("loads the next page on Show more and moves focus to the first new fragment", async () => {
    apiFetchMock
      .mockResolvedValueOnce(chunkPageFixture(FIRST_FIFTY, { total: 51 }))
      .mockResolvedValueOnce(chunkPageFixture([chunkFixture(50)], { page: 2, total: 51 }));
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    const added = await within(region()).findByText("Passage 50 of the lecture.");
    expect(apiFetchMock).toHaveBeenLastCalledWith(SECOND_PAGE_PATH);
    expect(rows()).toHaveLength(51);
    await waitFor(() => expect(added.closest("li")).toHaveFocus());
    expect(added.closest("li")).toHaveAttribute("tabindex", "-1");
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("offers Show more as a quiet button", async () => {
    apiFetchMock.mockResolvedValue(chunkPageFixture(FIRST_FIFTY, { total: 51 }));
    renderList();

    expect(await screen.findByRole("button", { name: "Show more" })).toHaveAttribute(
      "data-variant",
      "secondary",
    );
  });

  it("keeps the fragments when the next page fails, and loads it on another try", async () => {
    apiFetchMock
      .mockResolvedValueOnce(chunkPageFixture(FIRST_FIFTY, { total: 51 }))
      .mockRejectedValueOnce(new ApiError({ status: 503, code: "http_error", message: "x" }))
      .mockResolvedValueOnce(chunkPageFixture([chunkFixture(50)], { page: 2, total: 51 }));
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "More fragments could not be loaded.",
    );
    expect(rows()).toHaveLength(50);

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));

    expect(await within(region()).findByText("Passage 50 of the lecture.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports a failure to load and loads again on request", async () => {
    apiFetchMock
      .mockRejectedValueOnce(new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }))
      .mockResolvedValueOnce(chunkPageFixture([chunkFixture(0)]));
    renderList();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The API could not be reached. Check your connection and try again.",
    );
    const again = screen.getByRole("button", { name: "Try again" });
    expect(again).toHaveAttribute("data-variant", "secondary");

    await userEvent.click(again);

    expect(await within(region()).findByText("Passage 0 of the lecture.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // Try again had the focus and the fragments took its place.
    await waitFor(() =>
      expect(within(region()).getByRole("heading", { name: "Fragments" })).toHaveFocus(),
    );
  });

  it("names a server failure without its English message", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
    );
    renderList();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The fragments could not be loaded.",
    );
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
  });

  it("renders the text of a fragment as plain text", async () => {
    const markup = "<img src=x onerror=alert(1)>";
    apiFetchMock.mockResolvedValue(
      chunkPageFixture([chunkFixture(0, { heading: `${markup} heading`, content: markup })]),
    );
    renderList();

    expect(await within(region()).findByText(markup)).toBeVisible();
    expect(within(region()).getByText(`${markup} heading`)).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
  });

  it("speaks Russian", async () => {
    apiFetchMock.mockResolvedValue(
      chunkPageFixture([chunkFixture(0, { page_end: 2 }), ...FIRST_FIFTY.slice(1)], { total: 51 }),
    );
    renderList(READY, "ru");

    const fragments = region("Фрагменты");
    expect(await within(fragments).findByText("Страницы 1–2")).toBeInTheDocument();
    expect(within(fragments).getByText("Страница 3")).toBeInTheDocument();
    expect(within(fragments).getByRole("button", { name: "Показать ещё" })).toBeInTheDocument();
  });

  it("says the fragments come later in Russian", () => {
    renderList(documentFixture(1, { status: "processing" }), "ru");

    expect(
      within(region("Фрагменты")).getByText("Фрагменты появятся, когда файл будет обработан."),
    ).toBeInTheDocument();
  });

  it("says a failed document has no fragments in Russian", () => {
    renderList(documentFixture(1, { status: "failed", error_code: "pdf_unreadable" }), "ru");

    expect(
      within(region("Фрагменты")).getByText("Фрагментов нет: файл не удалось обработать."),
    ).toBeInTheDocument();
  });
});
