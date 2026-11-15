import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { defaultScheduler, notifyManager, type InfiniteData } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { ChunkPage, DocumentOut } from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";
import { renderWithIntl } from "@/test/render";
import { stubScrollIntoView } from "@/test/scroll-into-view";

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
const PAGE_SIZE = 50;
const FIRST_PAGE_PATH = pagePath(1);
const SECOND_PAGE_PATH = pagePath(2);
const FIRST_FIFTY = Array.from({ length: 50 }, (_, index) => chunkFixture(index));

function pagePath(page: number): string {
  return `/documents/${READY.id}/chunks?page=${page}&page_size=${PAGE_SIZE}`;
}

function renderList(
  document: DocumentOut = READY,
  locale: Locale = "en",
  fragment: number | null = null,
) {
  return renderWithIntl(<ChunkList document={document} fragment={fragment} />, { locale });
}

function region(name = "Passages"): HTMLElement {
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
      within(region()).getByText("Passages appear once the file is processed."),
    ).toBeInTheDocument();
    expect(within(region()).queryByRole("list")).not.toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("says a failed document has no fragments instead of promising them", () => {
    apiFetchMock.mockResolvedValue(chunkPageFixture([chunkFixture(0)]));
    renderList(documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true }));

    expect(
      within(region()).getByText("There are no passages because the file could not be processed."),
    ).toBeInTheDocument();
    expect(
      within(region()).queryByText("Passages appear once the file is processed."),
    ).not.toBeInTheDocument();
    expect(within(region()).queryByRole("list")).not.toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("shows that the fragments are loading", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderList();

    expect(within(region()).getByText("Loading passages…")).toBeInTheDocument();
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
      "More passages could not be loaded.",
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
      expect(within(region()).getByRole("heading", { name: "Passages" })).toHaveFocus(),
    );
  });

  it("names a server failure without its English message", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
    );
    renderList();

    expect(await screen.findByRole("alert")).toHaveTextContent("The passages could not be loaded.");
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

describe("ChunkList opened at a fragment", () => {
  let scrollIntoView: ReturnType<typeof stubScrollIntoView>;

  beforeEach(() => {
    apiFetchMock.mockReset();
    scrollIntoView = stubScrollIntoView();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    // Updates normally reach React in a zero-delay timer, which the fake clock runs a
    // millisecond late when a request ends inside a tick; a microtask keeps every step exact.
    notifyManager.setScheduler(queueMicrotask);
  });

  afterEach(() => {
    notifyManager.setScheduler(defaultScheduler);
    vi.useRealTimers();
  });

  /** Lets the time pass, with every request and update it brings. */
  async function pass(ms: number): Promise<void> {
    await act(() => vi.advanceTimersByTimeAsync(ms));
  }

  /** One page of a document that has `total` fragments, cut the way the API cuts them. */
  function fragmentPage(page: number, total: number): ChunkPage {
    const first = (page - 1) * PAGE_SIZE;
    const count = Math.min(PAGE_SIZE, total - first);
    const chunks = Array.from({ length: count }, (_, offset) => chunkFixture(first + offset));
    return chunkPageFixture(chunks, { page, total });
  }

  /**
   * Answers each page of a document that has `total` fragments. `answer` may stand in for the
   * API's answer to a page, for example to fail it; undefined leaves that page to the API.
   */
  function serveFragments(
    total: number,
    answer?: (page: number) => Promise<ChunkPage> | undefined,
  ): void {
    apiFetchMock.mockImplementation((path) => {
      const page = Number(new URLSearchParams(path.split("?")[1]).get("page"));
      return answer?.(page) ?? Promise.resolve(fragmentPage(page, total));
    });
  }

  function requestedPages(): string[] {
    return apiFetchMock.mock.calls.map(([path]) => path);
  }

  /** The row of the fragment at `index`, found by its text the way a reader finds it. */
  function rowOf(index: number): HTMLElement | null {
    return screen.getByText(`Passage ${index} of the lecture.`).closest("li");
  }

  /** Gives every element the height a laid-out row would have; jsdom lays nothing out. */
  function rowsAreTall(height: number): void {
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(height);
  }

  it("centres the fragment the address names in the window and gives it the focus", async () => {
    serveFragments(3);
    rowsAreTall(window.innerHeight);
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    renderList(READY, "en", 0);
    await pass(0);

    const row = rowOf(0);
    expect(row).toHaveAttribute("id", "fragment-0");
    expect(scrollIntoView).toHaveBeenCalledExactlyOnceWith({ block: "center" });
    expect(scrollIntoView.mock.contexts).toEqual([row]);
    expect(row).toHaveFocus();
    // Focusing must not scroll again and undo the centring.
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(requestedPages()).toEqual([pagePath(1)]);
  });

  it("shows a fragment taller than the window from its start, so its label stays in sight", async () => {
    serveFragments(3);
    rowsAreTall(window.innerHeight + 1);
    renderList(READY, "en", 1);
    await pass(0);

    expect(scrollIntoView).toHaveBeenCalledExactlyOnceWith({ block: "start" });
    expect(scrollIntoView.mock.contexts).toEqual([rowOf(1)]);
    expect(rowOf(1)).toHaveFocus();
  });

  it("labels the fragment the address names, and only that one", async () => {
    serveFragments(3);
    renderList(READY, "en", 1);
    await pass(0);

    expect(screen.getAllByText("The passage you opened")).toHaveLength(1);
    expect(rowOf(1)).toHaveTextContent("The passage you opened");
    expect(rows().map((row) => row.id)).toEqual(["fragment-0", "fragment-1", "fragment-2"]);
    // A label, not a live region: the page around the list keeps its one.
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("loads the pages up to a fragment on the third page in order, then goes there once", async () => {
    serveFragments(200);
    renderList(READY, "en", 120);
    await pass(0);

    expect(requestedPages()).toEqual([pagePath(1), pagePath(2), pagePath(3)]);
    const row = rowOf(120);
    expect(scrollIntoView.mock.contexts).toEqual([row]);
    expect(row).toHaveFocus();
    expect(row).toHaveTextContent("The passage you opened");

    await pass(60_000);

    expect(requestedPages()).toHaveLength(3);
    expect(scrollIntoView).toHaveBeenCalledOnce();
  });

  it("asks once for a page that fails, then leaves it to Show more and its error", async () => {
    let failed = false;
    serveFragments(200, (page) => {
      if (page !== 2 || failed) {
        return undefined;
      }
      failed = true;
      return Promise.reject(new ApiError({ status: 503, code: "http_error", message: "x" }));
    });
    renderList(READY, "en", 120);
    await pass(0);
    await pass(60_000);

    expect(requestedPages()).toEqual([pagePath(1), pagePath(2)]);
    expect(screen.getByRole("alert")).toHaveTextContent("More passages could not be loaded.");
    expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
    expect(rows()).toHaveLength(50);
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it.each([51, 120])(
    "loads nothing more for fragment %i of a document that has 51",
    async (fragment) => {
      serveFragments(51);
      renderList(READY, "en", fragment);
      await pass(0);
      await pass(60_000);

      expect(requestedPages()).toEqual([pagePath(1)]);
      expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
      expect(screen.queryByText("The passage you opened")).not.toBeInTheDocument();
      expect(scrollIntoView).not.toHaveBeenCalled();
    },
  );

  it("loads nothing for a document that is no longer ready, even with its first page kept", async () => {
    serveFragments(200);
    const { rerender } = renderList(READY, "en", null);
    await pass(0);

    // A re-index takes the document back to uploaded while its first page stays in memory.
    rerender(<ChunkList document={{ ...READY, status: "uploaded" }} fragment={120} />);
    await pass(60_000);

    expect(requestedPages()).toEqual([pagePath(1)]);
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("leaves the focus where the user has moved it while the pages load", async () => {
    const second = Promise.withResolvers<ChunkPage>();
    serveFragments(200, (page) => (page === 2 ? second.promise : undefined));
    renderWithIntl(
      <>
        <input aria-label="Notes" />
        <ChunkList document={READY} fragment={60} />
      </>,
    );
    await pass(0);

    screen.getByLabelText("Notes").focus();
    second.resolve(fragmentPage(2, 200));
    await pass(0);

    expect(rowOf(60)).toHaveTextContent("The passage you opened");
    expect(screen.getByLabelText("Notes")).toHaveFocus();
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("leaves Show more to move the focus as usual once the reader has arrived", async () => {
    serveFragments(51);
    renderList(READY, "en", 0);
    await pass(0);

    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await pass(0);

    expect(rowOf(50)).toHaveFocus();
    expect(scrollIntoView).toHaveBeenCalledOnce();
  });

  it("goes to the fragment once, however the list grows afterwards", async () => {
    serveFragments(51);
    const { queryClient } = renderList(READY, "en", 0);
    await pass(0);

    // The reader clicks away, and more fragments come in without Show more.
    rowOf(0)?.blur();
    act(() => {
      queryClient.setQueryData<InfiniteData<ChunkPage, number>>(
        queryKeys.documentChunks(READY.id),
        (data) =>
          data && {
            pages: [...data.pages, fragmentPage(2, 51)],
            pageParams: [...data.pageParams, 2],
          },
      );
    });
    await pass(0);

    expect(rows()).toHaveLength(51);
    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(rowOf(0)).not.toHaveFocus();
  });

  it("goes to another fragment when the address names one", async () => {
    serveFragments(3);
    const { rerender } = renderList(READY, "en", 0);
    await pass(0);
    rowOf(0)?.blur();

    rerender(<ChunkList document={READY} fragment={2} />);
    await pass(0);

    expect(rowOf(2)).toHaveFocus();
    expect(rowOf(2)).toHaveTextContent("The passage you opened");
    expect(rowOf(0)).not.toHaveTextContent("The passage you opened");
    expect(scrollIntoView.mock.contexts).toEqual([rowOf(0), rowOf(2)]);
  });

  it("labels the fragment the address names in Russian", async () => {
    serveFragments(3);
    renderList(READY, "ru", 1);
    await pass(0);

    expect(rowOf(1)).toHaveTextContent("Фрагмент, который вы открыли");
  });
});
