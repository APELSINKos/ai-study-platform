import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { defaultScheduler, notifyManager } from "@tanstack/react-query";
import type * as MotionModule from "motion/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { workspaceFixture } from "@/features/workspaces/test-fixtures";
import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { ChunkOut, DocumentOut, MetaOut, WorkspaceOut } from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";
import { renderWithIntl } from "@/test/render";

import { DocumentView } from "./document-view";
import {
  WORKSPACE_ID,
  chunkFixture,
  chunkPageFixture,
  documentFixture,
  readyDocumentFixture,
} from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }));

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

// The rails stay still, so no animation outlives a test.
vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof MotionModule>()),
  useReducedMotion: () => true,
}));

const apiFetchMock = vi.mocked(apiFetch);

const META_PATH = "/meta";
const META: MetaOut = {
  max_upload_bytes: 20_971_520,
  allowed_extensions: [".pdf", ".md", ".txt"],
  max_pdf_pages: 500,
  max_active_documents_per_user: 10,
  max_storage_bytes_per_user: 1_073_741_824,
  ai: { mode: "offline", chat_model: "mock-heuristic-v1", embedding_model: "mock-hashing-v1" },
};

const WORKSPACE = workspaceFixture(1, { name: "Organic chemistry" });
const SUMMARY =
  "Normal forms remove redundancy from relations. The lecture walks from the first to the third normal form.";
const READY = readyDocumentFixture(1, {
  title: "Normal forms",
  summary: SUMMARY,
  topics: ["Functional dependencies", "Third normal form", "Decomposition"],
  difficulty: "medium",
  estimated_study_minutes: 25,
});
const FAILED = documentFixture(1, {
  status: "failed",
  error_code: "pdf_unreadable",
  can_retry: true,
});
const DOCUMENT_PATH = `/documents/${READY.id}`;
const CHUNKS_PATH = `${DOCUMENT_PATH}/chunks?page=1&page_size=50`;

function renderView(id = READY.id, locale: Locale = "en") {
  return renderWithIntl(<DocumentView id={id} />, { locale });
}

interface Answers {
  chunks?: ChunkOut[];
  workspace?: WorkspaceOut;
  /** Stands in for the API's answer to a retry, for example to fail it. */
  retry?: () => Promise<unknown>;
  /** Stands in for the API's answer to a delete. */
  remove?: () => Promise<unknown>;
}

/** Answers like the API would: a retry queues the document again, a delete succeeds. */
function serve(
  initial: DocumentOut,
  { chunks = [chunkFixture(0)], workspace = WORKSPACE, retry, remove }: Answers = {},
) {
  let current = initial;
  apiFetchMock.mockImplementation(async (path, init) => {
    if (path === META_PATH) {
      return META;
    }
    if (path.startsWith("/workspaces/")) {
      return workspace;
    }
    if (path.includes("/chunks")) {
      return chunkPageFixture(chunks);
    }
    if (init?.method === "POST") {
      if (retry) {
        return retry();
      }
      current = { ...current, status: "uploaded", error_code: null, can_retry: false };
    }
    if (init?.method === "DELETE") {
      return remove ? remove() : undefined;
    }
    return current;
  });
  return {
    /** What the next request for the document finds. */
    becomes(next: DocumentOut) {
      current = next;
    },
  };
}

function requestsFor(predicate: (path: string) => boolean): number {
  return apiFetchMock.mock.calls.filter(([path]) => predicate(path)).length;
}

function primaryActions(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-variant="primary"]')).map(
    (element) => element.textContent ?? "",
  );
}

function railOnPage(): Element | null {
  return document.querySelector("svg[aria-hidden='true'] [data-stage]");
}

async function expectStatus(text: string): Promise<void> {
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(text));
}

describe("DocumentView", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("shows that the document is loading under the page's one heading", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderView();

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "Document" })).toBeInTheDocument();
    expect(screen.getByText("Loading the document…")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("asks for the document the address names", async () => {
    serve(READY);
    renderView();

    await screen.findByRole("heading", { level: 1, name: "Normal forms" });
    expect(apiFetchMock).toHaveBeenCalledWith(DOCUMENT_PATH);
  });

  it("keeps an odd id inside its own path segment", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 422, code: "validation_error", message: "x" }),
    );
    renderView("../auth/me");

    await screen.findByRole("heading", { level: 1, name: "Document not found" });
    expect(apiFetchMock).toHaveBeenCalledWith("/documents/..%2Fauth%2Fme");
  });

  it("shows the title in the display serif, with the file it came from", async () => {
    serve(READY);
    renderView();

    const title = await screen.findByRole("heading", { level: 1, name: "Normal forms" });
    expect(title).toHaveClass("font-display", "break-words");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const filename = screen.getByText("lecture-1.pdf");
    expect(filename).toHaveAttribute("title", "lecture-1.pdf");
    expect(filename).toHaveClass("truncate");
    expect(screen.getByText("2.4 MB").tagName).toBe("SPAN");
  });

  it("names a document by its file until it has a title", async () => {
    serve(documentFixture(1, { original_filename: "week-3 notes.md", status: "processing" }));
    renderView();

    expect(
      await screen.findByRole("heading", { level: 1, name: "week-3 notes.md" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("week-3 notes.md")).toHaveLength(1);
  });

  it("shows the summary and the topics of the analysis", async () => {
    serve(READY);
    renderView();

    expect(await screen.findByText(SUMMARY)).toBeInTheDocument();
    const topics = screen.getByRole("region", { name: "Topics" });
    expect(
      within(topics)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["Functional dependencies", "Third normal form", "Decomposition"]);
  });

  it("states the facts of the analysis", async () => {
    serve(READY);
    renderView();

    const details = await screen.findByRole("region", { name: "Details" });
    expect(within(details).getByText("Medium")).toBeInTheDocument();
    expect(within(details).getByText("25 minutes")).toBeInTheDocument();
    expect(await within(details).findByText("Offline analysis")).toBeInTheDocument();
  });

  it("leaves out the analysis while the document has none", async () => {
    serve(documentFixture(1, { status: "processing" }));
    renderView();

    await screen.findByRole("heading", { level: 1, name: "lecture-1.pdf" });
    expect(screen.queryByRole("region", { name: "Topics" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Details" })).not.toBeInTheDocument();
  });

  it("leads back to the workspace the document belongs to from the margin", async () => {
    serve(READY);
    renderView();

    const breadcrumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    const link = await within(breadcrumb).findByRole("link", { name: "Organic chemistry" });
    expect(link).toHaveAttribute("href", `/workspaces/${WORKSPACE_ID}`);
    expect(breadcrumb).toHaveClass("margin-note");
    expect(apiFetchMock).toHaveBeenCalledWith(`/workspaces/${WORKSPACE_ID}`);
  });

  it("still leads back to the workspace when its name cannot be loaded", async () => {
    serve(READY);
    const answer = apiFetchMock.getMockImplementation();
    apiFetchMock.mockImplementation((path, init) =>
      path.startsWith("/workspaces/")
        ? Promise.reject(new ApiError({ status: 503, code: "http_error", message: "x" }))
        : (answer?.(path, init) ?? Promise.resolve(undefined)),
    );
    renderView();

    const breadcrumb = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(await within(breadcrumb).findByRole("link", { name: "Workspace" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE_ID}`,
    );
  });

  it("says a ready document is ready in the page's one live region, with no rail", async () => {
    serve(READY);
    renderView();

    await expectStatus("Ready");
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(railOnPage()).toBeNull();
  });

  it.each([
    ["uploaded", "In the queue"],
    ["processing", "Reading and analysing"],
    ["indexing", "Preparing for search"],
  ] as const)("tells the stage of a %s document beside its rail", async (status, label) => {
    serve(documentFixture(1, { status }));
    renderView();

    await expectStatus(label);
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(railOnPage()).not.toBeNull();
    expect(screen.getByText(label).closest("p")).toHaveClass("text-ink");
  });

  it("asks for no fragments until the document is ready", async () => {
    serve(documentFixture(1, { status: "indexing" }));
    renderView();

    const fragments = await screen.findByRole("region", { name: "Fragments" });
    expect(
      within(fragments).getByText("Fragments appear once the file is processed."),
    ).toBeInTheDocument();
    expect(requestsFor((path) => path.includes("/chunks"))).toBe(0);
  });

  it("lists the fragments of a ready document", async () => {
    serve(READY, { chunks: [chunkFixture(0), chunkFixture(1)] });
    renderView();

    const fragments = await screen.findByRole("region", { name: "Fragments" });
    expect(await within(fragments).findByText("Passage 1 of the lecture.")).toBeInTheDocument();
    expect(apiFetchMock).toHaveBeenCalledWith(CHUNKS_PATH);
  });

  it("says why a document failed and offers to retry it", async () => {
    serve(FAILED);
    renderView();

    await expectStatus("Failed");
    const reason = screen.getByText("The PDF could not be read. The file may be damaged.");
    expect(reason).toHaveClass("text-margin");
    expect(screen.getByRole("status")).toContainElement(reason);
    expect(screen.getByRole("button", { name: "Retry processing" })).toHaveAttribute(
      "data-variant",
      "secondary",
    );
  });

  it("retries a failed document: the page moves on and focus goes to the title", async () => {
    serve(FAILED);
    renderView();

    await userEvent.click(await screen.findByRole("button", { name: "Retry processing" }));

    await expectStatus("In the queue");
    expect(apiFetchMock).toHaveBeenCalledWith(`/documents/${FAILED.id}/retry`, {
      method: "POST",
    });
    expect(screen.queryByRole("button", { name: "Retry processing" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("The PDF could not be read. The file may be damaged."),
    ).not.toBeInTheDocument();
    const title = screen.getByRole("heading", { level: 1, name: "lecture-1.pdf" });
    await waitFor(() => expect(title).toHaveFocus());
    expect(title).toHaveAttribute("tabindex", "-1");
  });

  it("says why a retry was refused and keeps Retry on offer", async () => {
    serve(FAILED, {
      retry: () =>
        Promise.reject(
          new ApiError({ status: 429, code: "rate_limited", message: "x", retryAfterSeconds: 120 }),
        ),
    });
    renderView();
    const retry = await screen.findByRole("button", { name: "Retry processing" });

    await userEvent.click(retry);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many attempts. Try again in 2 minutes.",
    );
    expect(retry).toBeInTheDocument();
    expect(retry).toHaveFocus();
  });

  it("notes that a stalled document is taking longer than usual, with Retry", async () => {
    serve(documentFixture(1, { status: "processing", can_retry: true }));
    renderView();

    await expectStatus("Reading and analysing");
    expect(screen.getByRole("status")).toHaveTextContent("This is taking longer than usual.");
    expect(screen.getByRole("button", { name: "Retry processing" })).toBeInTheDocument();
  });

  it("says a retry is coming after the AI service did not answer", async () => {
    serve(documentFixture(1, { status: "uploaded", error_code: "ai_unavailable" }));
    renderView();

    await expectStatus("Retrying soon");
    expect(screen.queryByRole("button", { name: "Retry processing" })).not.toBeInTheDocument();
  });

  it("offers no primary action", async () => {
    serve(READY);
    renderView();

    await screen.findByText("Passage 0 of the lecture.");
    expect(primaryActions()).toEqual([]);
  });

  it("renders the text of the file as plain text", async () => {
    const markup = "<img src=x onerror=alert(1)>";
    serve(
      readyDocumentFixture(1, {
        title: markup,
        summary: `${markup} summary`,
        topics: [`${markup} topic`],
      }),
      { chunks: [chunkFixture(0, { heading: `${markup} heading`, content: `${markup} content` })] },
    );
    renderView();

    expect(await screen.findByRole("heading", { level: 1, name: markup })).toBeVisible();
    expect(screen.getByText(`${markup} summary`)).toBeVisible();
    expect(screen.getByText(`${markup} topic`)).toBeVisible();
    expect(await screen.findByText(`${markup} content`)).toBeVisible();
    expect(screen.getByText(`${markup} heading`)).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
  });

  it("says a document that does not exist was not found", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "document_not_found", message: "Not found." }),
    );
    renderView();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Document not found" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("It may have been deleted, or the link is incomplete."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All workspaces" })).toHaveAttribute(
      "href",
      "/workspaces",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Not found.")).not.toBeInTheDocument();
  });

  it("treats an address that is no document id as not found", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 422, code: "validation_error", message: "x" }),
    );
    renderView("not-a-uuid");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Document not found" }),
    ).toBeInTheDocument();
  });

  it("reports any other failure and loads again on request", async () => {
    serve(READY);
    apiFetchMock.mockRejectedValueOnce(
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }),
    );
    renderView();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The API could not be reached. Check your connection and try again.",
    );
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Normal forms" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names a server failure without its English message", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
    );
    renderView();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This document could not be loaded.",
    );
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
  });

  it("turns into not found once the document is gone, though a copy is cached", async () => {
    serve(READY);
    const { queryClient } = renderView();
    await screen.findByRole("heading", { level: 1, name: "Normal forms" });

    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "document_not_found", message: "x" }),
    );
    await act(() =>
      queryClient.refetchQueries({ queryKey: queryKeys.document(READY.id), exact: true }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Document not found" }),
    ).toBeInTheDocument();
  });

  it("keeps showing the document when a later refresh fails for a passing reason", async () => {
    serve(READY);
    const { queryClient } = renderView();
    await screen.findByRole("heading", { level: 1, name: "Normal forms" });

    apiFetchMock.mockRejectedValue(new ApiError({ status: 503, code: "http_error", message: "x" }));
    await act(() =>
      queryClient.refetchQueries({ queryKey: queryKeys.document(READY.id), exact: true }),
    );

    await waitFor(() =>
      expect(queryClient.getQueryState(queryKeys.document(READY.id))?.status).toBe("error"),
    );
    expect(screen.getByRole("heading", { level: 1, name: "Normal forms" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("drops a copy it can no longer refresh once a request is refused", async () => {
    serve(documentFixture(1, { status: "processing" }));
    const { queryClient } = renderView();
    await screen.findByRole("heading", { level: 1, name: "lecture-1.pdf" });

    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 401, code: "not_authenticated", message: "x" }),
    );
    await act(() =>
      queryClient.refetchQueries({ queryKey: queryKeys.document(READY.id), exact: true }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your session has ended. Sign in again to continue.",
    );
    expect(screen.queryByRole("heading", { level: 1, name: "lecture-1.pdf" })).toBeNull();
  });

  it("speaks Russian", async () => {
    serve(READY);
    renderView(READY.id, "ru");

    await expectStatus("Готов");
    expect(screen.getByRole("region", { name: "Темы" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Подробности" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Фрагменты" })).toBeInTheDocument();
    expect(screen.getByText("2,4 МБ")).toBeInTheDocument();
    const breadcrumb = screen.getByRole("navigation", { name: "Навигационная цепочка" });
    expect(
      await within(breadcrumb).findByRole("link", { name: "Organic chemistry" }),
    ).toBeVisible();
  });

  it("tells the stage and offers Retry in Russian", async () => {
    serve(FAILED);
    renderView(READY.id, "ru");

    await expectStatus("Не обработан");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Не удалось прочитать PDF. Возможно, файл повреждён.",
    );
    expect(screen.getByRole("button", { name: "Повторить обработку" })).toBeInTheDocument();
    expect(screen.getByText("Фрагментов нет: файл не удалось обработать.")).toBeInTheDocument();
  });

  it("is loading and not found in Russian", async () => {
    apiFetchMock.mockReturnValueOnce(new Promise(() => {}));
    const { unmount } = renderView(READY.id, "ru");
    expect(screen.getByRole("heading", { level: 1, name: "Документ" })).toBeInTheDocument();
    expect(screen.getByText("Загрузка документа…")).toBeInTheDocument();
    unmount();

    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "document_not_found", message: "x" }),
    );
    renderView(READY.id, "ru");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Документ не найден" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Все пространства" })).toBeInTheDocument();
  });
});

describe("DocumentView download and delete", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    replace.mockClear();
  });

  async function confirmDelete(): Promise<HTMLElement> {
    await userEvent.click(await screen.findByRole("button", { name: "Delete document" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete this document?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete document" }));
    return dialog;
  }

  it.each([
    ["ready", READY],
    ["on its way", documentFixture(1, { status: "processing" })],
    ["failed", FAILED],
  ])(
    "offers to download or delete a document that is %s, with no primary action",
    async (_, document) => {
      serve(document);
      renderView();

      expect(await screen.findByRole("button", { name: "Download original" })).toHaveAttribute(
        "data-variant",
        "secondary",
      );
      expect(screen.getByRole("button", { name: "Delete document" })).toHaveAttribute(
        "data-variant",
        "danger",
      );
      expect(primaryActions()).toEqual([]);
    },
  );

  it("asks before deleting and names the file", async () => {
    serve(READY);
    renderView();

    await userEvent.click(await screen.findByRole("button", { name: "Delete document" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Delete this document?" });
    expect(dialog).toHaveAccessibleDescription(
      "“lecture-1.pdf” will be deleted. This cannot be undone.",
    );
    expect(requestsFor((path) => path === DOCUMENT_PATH)).toBe(1);
  });

  it("deletes the document after asking, then goes back to its workspace", async () => {
    serve(READY);
    renderView();

    await confirmDelete();

    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/workspaces/${WORKSPACE_ID}`));
    expect(apiFetchMock).toHaveBeenCalledWith(DOCUMENT_PATH, { method: "DELETE" });
    // The load and the delete only: the page's copy is dropped, not fetched again to a 404.
    expect(requestsFor((path) => path === DOCUMENT_PATH)).toBe(2);
  });

  it("forgets the deleted document with its fragments", async () => {
    serve(READY);
    const { queryClient } = renderView();
    await screen.findByText("Passage 0 of the lecture.");

    await confirmDelete();

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(queryClient.getQueryData(queryKeys.document(READY.id))).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.documentChunks(READY.id))).toBeUndefined();
  });

  it("keeps the question open with a translated error when the delete fails", async () => {
    serve(READY, {
      remove: () =>
        Promise.reject(
          new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
        ),
    });
    renderView();

    const dialog = await confirmDelete();

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The document could not be deleted. Try again.",
    );
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("treats a document deleted elsewhere as deleted", async () => {
    serve(READY, {
      remove: () =>
        Promise.reject(new ApiError({ status: 404, code: "document_not_found", message: "x" })),
    });
    renderView();

    await confirmDelete();

    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/workspaces/${WORKSPACE_ID}`));
  });

  it("offers to download and delete in Russian", async () => {
    serve(READY);
    renderView(READY.id, "ru");

    expect(await screen.findByRole("button", { name: "Скачать оригинал" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Удалить документ" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Удалить этот документ?" });
    expect(dialog).toHaveAccessibleDescription(
      "Файл «lecture-1.pdf» будет удалён. Это нельзя отменить.",
    );
  });
});

describe("DocumentView while the document is processed", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    replace.mockClear();
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

  const isDocumentPath = (path: string) => path === DOCUMENT_PATH;
  const isChunksPath = (path: string) => path.includes("/chunks");

  /** How many times the page has asked for the document, apart from deleting it. */
  function documentLoads(): number {
    return apiFetchMock.mock.calls.filter(([path, init]) => isDocumentPath(path) && !init).length;
  }

  /**
   * Serves a document whose delete the server carries out at once but answers only when told,
   * the way a slow connection delivers it. From the delete on, the document is gone.
   */
  function serveSlowDelete(initial: DocumentOut): { answerDelete: () => void } {
    let deleted = false;
    let answer = () => {};
    serve(initial, {
      remove: () => {
        deleted = true;
        return new Promise((resolve) => {
          answer = () => resolve(undefined);
        });
      },
    });
    const served = apiFetchMock.getMockImplementation();
    apiFetchMock.mockImplementation((path, init) =>
      deleted && isDocumentPath(path) && !init
        ? Promise.reject(new ApiError({ status: 404, code: "document_not_found", message: "x" }))
        : (served?.(path, init) ?? Promise.resolve(undefined)),
    );
    return { answerDelete: () => answer() };
  }

  /**
   * Asks to delete the document and confirms. Plain events: user-event waits on a timer that the
   * fake clock would hold forever.
   */
  function confirmDelete(): void {
    fireEvent.click(screen.getByRole("button", { name: "Delete document" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete this document?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete document" }));
  }

  it("moves on stage by stage and asks for the fragments once when it is done", async () => {
    const processing = documentFixture(1, { status: "processing" });
    const api = serve(processing, { chunks: [chunkFixture(0)] });
    renderView();
    await pass(0);
    expect(screen.getByRole("status")).toHaveTextContent("Reading and analysing");

    api.becomes({ ...READY, status: "indexing", chunk_count: null, processed_at: null });
    await pass(2000);
    expect(screen.getByRole("status")).toHaveTextContent("Preparing for search");
    expect(screen.getByText(SUMMARY)).toBeInTheDocument();
    expect(requestsFor(isChunksPath)).toBe(0);

    api.becomes(READY);
    await pass(2000);
    // The fragments are asked for only after the page has seen the document ready.
    await pass(0);
    expect(screen.getByRole("status")).toHaveTextContent("Ready");
    expect(screen.getByText("Passage 0 of the lecture.")).toBeInTheDocument();
    expect(requestsFor(isChunksPath)).toBe(1);

    await pass(60_000);
    expect(requestsFor(isDocumentPath)).toBe(3);
    expect(requestsFor(isChunksPath)).toBe(1);
  });

  it("stops asking once the document is refused, and says it is gone", async () => {
    serve(documentFixture(1, { status: "processing" }));
    renderView();
    await pass(0);
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "document_not_found", message: "x" }),
    );

    await pass(2000);
    expect(screen.getByRole("heading", { level: 1, name: "Document not found" })).toBeVisible();

    await pass(60_000);
    expect(requestsFor(isDocumentPath)).toBe(2);
  });

  it("stops asking for the document while deleting it, then leaves for its workspace", async () => {
    const { answerDelete } = serveSlowDelete(documentFixture(1, { status: "processing" }));
    renderView();
    await pass(0);

    confirmDelete();
    // The server has deleted the document, but its answer is still on the way.
    await pass(2000);
    expect(documentLoads()).toBe(1);

    answerDelete();
    await pass(0);
    expect(replace).toHaveBeenCalledWith(`/workspaces/${WORKSPACE_ID}`);

    // The workspace's page takes a moment to open, and the document stays until it does.
    await pass(2000);
    expect(documentLoads()).toBe(1);
    expect(
      screen.getByRole("heading", { level: 1, name: "lecture-1.pdf", hidden: true }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 1, name: "Document not found", hidden: true }),
    ).not.toBeInTheDocument();
  });

  it("asks for the document again once a delete fails", async () => {
    serve(documentFixture(1, { status: "processing" }), {
      remove: () =>
        Promise.reject(new ApiError({ status: 500, code: "internal_error", message: "x" })),
    });
    renderView();
    await pass(0);

    confirmDelete();
    await pass(0);
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "The document could not be deleted. Try again.",
    );
    const loads = documentLoads();

    await pass(2000);

    expect(documentLoads()).toBe(loads + 1);
  });
});
