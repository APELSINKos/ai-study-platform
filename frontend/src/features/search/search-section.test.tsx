import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WORKSPACE_ID } from "@/features/documents/test-fixtures";
import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { MetaOut, SearchResults } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { SearchSection } from "./search-section";
import { searchHitFixture, searchResultsFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

// One function for every render, so that a test sees each navigation the section asked for.
const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));

const apiFetchMock = vi.mocked(apiFetch);

const WORKSPACE_URL = `/workspaces/${WORKSPACE_ID}`;
const META_PATH = "/meta";
const META: MetaOut = {
  max_upload_bytes: 20_971_520,
  allowed_extensions: [".pdf", ".md", ".txt"],
  max_pdf_pages: 500,
  max_active_documents_per_user: 10,
  max_storage_bytes_per_user: 1_073_741_824,
  ai: { mode: "offline", chat_model: "mock-heuristic-v1", embedding_model: "mock-hashing-v1" },
  search: { max_query_chars: 200 },
};

function searchPath(query: string): string {
  const params = new URLSearchParams({ workspace_id: WORKSPACE_ID, q: query, limit: "10" });
  return `/search?${params.toString()}`;
}

/** Answers /meta with `meta`, and every search with what `answer` gives. */
function serve(
  answer: () => Promise<SearchResults> = async () => searchResultsFixture(3),
  meta: MetaOut = META,
) {
  apiFetchMock.mockImplementation((path) =>
    path === META_PATH ? Promise.resolve(meta) : answer(),
  );
}

function searchCalls() {
  return apiFetchMock.mock.calls.filter(([path]) => path.startsWith("/search"));
}

/** Renders the section for the query an address holds; `showQuery` is a later navigation. */
function renderSection(query: string | null, locale: Locale = "en") {
  const rendered = renderWithIntl(<SearchSection workspaceId={WORKSPACE_ID} query={query} />, {
    locale,
  });
  return {
    ...rendered,
    showQuery: (next: string | null) =>
      rendered.rerender(<SearchSection workspaceId={WORKSPACE_ID} query={next} />),
  };
}

function region(name = "Search"): HTMLElement {
  return screen.getByRole("region", { name });
}

function searchbox(name = "Words to look for"): HTMLElement {
  return screen.getByRole("searchbox", { name });
}

function searchButton(name = "Search"): HTMLElement {
  return within(screen.getByRole("search")).getByRole("button", { name });
}

function apiError(status: number, code: string, retryAfterSeconds: number | null = null) {
  return new ApiError({ status, code, message: "The backend's own English.", retryAfterSeconds });
}

describe("SearchSection", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    push.mockReset();
    replace.mockReset();
  });

  it("is a region with a search form, both named by the section's heading", () => {
    serve();
    renderSection(null);

    expect(within(region()).getByRole("heading", { level: 2, name: "Search" })).toBeInTheDocument();
    expect(within(region()).getByRole("search", { name: "Search" })).toBeInTheDocument();
    expect(searchbox()).toHaveValue("");
    expect(searchButton()).toHaveAttribute("type", "submit");
  });

  it("offers no primary action: Search is a quiet button and Clear a ghost one", async () => {
    serve();
    renderSection("light");

    await screen.findByText("3 passages match.");
    expect(searchButton()).toHaveAttribute("data-variant", "secondary");
    expect(screen.getByRole("button", { name: "Clear" })).toHaveAttribute("data-variant", "ghost");
    expect(document.querySelector('[data-variant="primary"]')).toBeNull();
  });

  it("shows nothing under the form and asks for nothing until there is a query", async () => {
    serve();
    renderSection(null);

    await waitFor(() => expect(searchbox()).toHaveAttribute("maxLength", "200"));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
    expect(searchCalls()).toHaveLength(0);
  });

  it("lets the query be as long as /meta allows", async () => {
    serve();
    renderSection(null);

    await waitFor(() => expect(searchbox()).toHaveAttribute("maxLength", "200"));
  });

  it("puts the query into the address as a new history entry, without scrolling", async () => {
    serve();
    renderSection(null);

    await userEvent.type(searchbox(), "light reactions");
    await userEvent.click(searchButton());

    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith(`${WORKSPACE_URL}?q=light%20reactions`, { scroll: false });
    expect(replace).not.toHaveBeenCalled();
    // The address changes the query; the search follows from it.
    expect(searchCalls()).toHaveLength(0);
  });

  it("searches on Enter too, without the spaces around the query", async () => {
    serve();
    renderSection(null);

    await userEvent.type(searchbox(), "  glucose & sugar {Enter}");

    expect(push).toHaveBeenCalledWith(`${WORKSPACE_URL}?q=glucose%20%26%20sugar`, {
      scroll: false,
    });
  });

  it("puts a broken character into the address as a replacement character", async () => {
    serve();
    renderSection(null);

    // Half of an emoji, as a paste cut in the wrong place can leave it.
    fireEvent.change(searchbox(), { target: { value: "light \uD83D" } });
    await userEvent.click(searchButton());

    expect(push).toHaveBeenCalledWith(`${WORKSPACE_URL}?q=light%20%EF%BF%BD`, { scroll: false });
  });

  it("never searches for blank text", async () => {
    serve();
    renderSection(null);

    await userEvent.type(searchbox(), "   {Enter}");
    await userEvent.click(searchButton());

    expect(push).not.toHaveBeenCalled();
    expect(searchCalls()).toHaveLength(0);
  });

  it("searches the workspace for the query of the address and says how many passages match", async () => {
    serve();
    renderSection("light");

    expect(
      await within(region()).findByRole("list", { name: "Search results" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("3 passages match.");
    expect(searchbox()).toHaveValue("light");
    expect(searchCalls()).toEqual([[searchPath("light"), { signal: expect.any(AbortSignal) }]]);
  });

  it("follows a new query of the address into the box, and the focus stays there", async () => {
    serve();
    const { showQuery } = renderSection(null);
    await userEvent.click(searchbox());

    showQuery("light");

    expect(searchbox()).toHaveValue("light");
    expect(searchbox()).toHaveFocus();
    expect(await screen.findByText("3 passages match.")).toBeInTheDocument();

    // Back to the address without a search.
    showQuery(null);

    expect(searchbox()).toHaveValue("");
    expect(searchbox()).toHaveFocus();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("shows an earlier search again from memory when the address returns to it", async () => {
    serve();
    const { showQuery } = renderSection("light");
    await screen.findByText("3 passages match.");

    showQuery("glucose");
    await waitFor(() => expect(searchCalls()).toHaveLength(2));
    await screen.findByText("3 passages match.");
    showQuery("light");

    expect(await screen.findByText("3 passages match.")).toBeInTheDocument();
    expect(searchCalls()).toHaveLength(2);
  });

  it("searches again for an unchanged query, without a new history entry", async () => {
    serve();
    renderSection("light");
    await screen.findByText("3 passages match.");

    await userEvent.type(searchbox(), " ");
    await userEvent.click(searchButton());

    await waitFor(() => expect(searchCalls()).toHaveLength(2));
    expect(push).not.toHaveBeenCalled();
    expect(await screen.findByText("3 passages match.")).toBeInTheDocument();
  });

  it("empties the status line while the same search runs again, so that its answer is announced anew", async () => {
    let attempts = 0;
    serve(() => {
      attempts += 1;
      return attempts === 1 ? Promise.resolve(searchResultsFixture(3)) : new Promise(() => {});
    });
    renderSection("light");
    await screen.findByText("3 passages match.");

    await userEvent.click(searchButton());

    expect(await within(region()).findByText("Searching…")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("shows a running search as a busy skeleton, with a busy button and an empty status line", async () => {
    serve(() => new Promise(() => {}));
    renderSection("light");

    const loading = await within(region()).findByText("Searching…");
    expect(loading.closest("[aria-busy='true']")).not.toBeNull();
    expect(searchButton()).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("ignores Enter and clicks while a search runs", async () => {
    serve(() => new Promise(() => {}));
    renderSection("light");
    await waitFor(() => expect(searchButton()).toHaveAttribute("aria-busy", "true"));

    await userEvent.clear(searchbox());
    await userEvent.type(searchbox(), "glucose{Enter}");
    await userEvent.click(searchButton());

    expect(push).not.toHaveBeenCalled();
    expect(searchCalls()).toHaveLength(1);
  });

  it("ignores Enter while the address is changing", async () => {
    serve();
    // A navigation that has not finished yet.
    push.mockReturnValue(new Promise(() => {}));
    renderSection(null);

    await userEvent.type(searchbox(), "light{Enter}");
    await waitFor(() => expect(searchButton()).toHaveAttribute("aria-busy", "true"));
    await userEvent.type(searchbox(), "{Enter}");

    expect(push).toHaveBeenCalledTimes(1);
  });

  it("clears the search from the address, empties the box and puts the focus in it", async () => {
    serve();
    const { showQuery } = renderSection("light");
    await screen.findByText("3 passages match.");

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(replace).toHaveBeenCalledWith(WORKSPACE_URL, { scroll: false });
    expect(push).not.toHaveBeenCalled();
    expect(searchbox()).toHaveValue("");
    expect(searchbox()).toHaveFocus();

    showQuery(null);

    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
    expect(searchbox()).toHaveFocus();
  });

  it("offers Clear only while the address holds a search", async () => {
    serve();
    const { showQuery } = renderSection(null);

    await userEvent.type(searchbox(), "light");

    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();

    showQuery("light");

    expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument();
  });

  it("says when no passage matches", async () => {
    serve(async () => searchResultsFixture(0));
    renderSection("xylophone");

    expect(await screen.findByText("No passages match.")).toHaveAttribute("role", "status");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("speaks of the closest passages when the search returned as many as it can", async () => {
    serve(async () => searchResultsFixture(10));
    renderSection("light");

    expect(await screen.findByText("The 10 closest passages.")).toHaveAttribute("role", "status");
    expect(within(region()).getAllByRole("listitem")).toHaveLength(10);
  });

  it("says how many passages match when the search returned fewer than it can", async () => {
    serve(async () => searchResultsFixture(9));
    renderSection("light");

    expect(await screen.findByText("9 passages match.")).toHaveAttribute("role", "status");
  });

  it("notes what the search could not cover, under the line that sums it up", async () => {
    serve(async () => searchResultsFixture(2, { pending_document_count: 1 }));
    renderSection("light");

    const note = await screen.findByText(
      "1 file is still being processed — search again once it is ready.",
    );
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("2 passages match.");
    expect(status.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(
      note.compareDocumentPosition(screen.getByRole("list")) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("reports a failed search and runs it again from the button", async () => {
    let attempts = 0;
    serve(async () => {
      attempts += 1;
      if (attempts === 1) {
        throw apiError(429, "rate_limited", 30);
      }
      return searchResultsFixture(3);
    });
    renderSection("light");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many searches. Try again in 30 seconds.",
    );
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    await userEvent.click(searchButton());

    expect(await screen.findByText("3 passages match.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it.each([
    [apiError(429, "rate_limited", 120), "Too many searches. Try again in 2 minutes."],
    [
      apiError(0, NETWORK_ERROR_CODE),
      "The API could not be reached. Check your connection and try again.",
    ],
    [apiError(404, "workspace_not_found"), "This workspace no longer exists."],
    [apiError(503, "search_unavailable"), "Search failed. Try again."],
  ])("words a failed search by its code: %s", async (error, expected) => {
    serve(async () => {
      throw error;
    });
    renderSection("light");

    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(screen.queryByText("The backend's own English.")).not.toBeInTheDocument();
  });

  it.each([
    ["the built-in embeddings", META, "Similar words"],
    [
      "a real embedding model",
      {
        ...META,
        ai: { mode: "live", chat_model: "gpt-4o-mini", embedding_model: "text-embedding-3-small" },
      },
      "Similar meaning",
    ],
  ] as const)(
    "names passages found by %s after what /meta reports",
    async (_, meta: MetaOut, label) => {
      const hit = searchHitFixture(1, { matched_by: ["keyword", "semantic"], similarity: 0.4 });
      serve(async () => searchResultsFixture(1, { results: [hit] }), meta);
      renderSection("light");

      const row = await within(region()).findByRole("listitem");
      await waitFor(() => expect(row).toHaveTextContent(label));
      expect(row).toHaveTextContent("Matching words");
      expect(row.querySelector("mark")).toHaveTextContent("light");
    },
  );

  it("speaks Russian", async () => {
    serve();
    renderSection("light", "ru");

    const section = region("Поиск");
    expect(within(section).getByRole("search", { name: "Поиск" })).toBeInTheDocument();
    expect(searchbox("Слова для поиска")).toHaveValue("light");
    expect(await screen.findByText("Запросу соответствуют 3 фрагмента.")).toHaveAttribute(
      "role",
      "status",
    );
    expect(searchButton("Найти")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Очистить" })).toBeInTheDocument();
    expect(within(section).getByRole("list", { name: "Результаты поиска" })).toBeInTheDocument();
  });

  it("is searching and failing in Russian", async () => {
    serve(() => new Promise(() => {}));
    const { unmount } = renderSection("light", "ru");
    expect(await screen.findByText("Идёт поиск…")).toBeInTheDocument();
    unmount();

    serve(async () => {
      throw apiError(500, "internal_error");
    });
    renderSection("light", "ru");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Поиск не удался. Попробуйте ещё раз.",
    );
  });
});
