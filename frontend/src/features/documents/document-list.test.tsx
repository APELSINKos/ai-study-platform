import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type * as MotionModule from "motion/react";
import { useRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { DocumentOut, DocumentStatus } from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";
import { renderWithIntl } from "@/test/render";

import { DocumentList } from "./document-list";
import {
  WORKSPACE_ID,
  documentFixture,
  documentPageFixture,
  readyDocumentFixture,
} from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

// The rails stay still, so no animation outlives a test.
vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof MotionModule>()),
  useReducedMotion: () => true,
}));

const apiFetchMock = vi.mocked(apiFetch);

const FIRST_PAGE_PATH = `/workspaces/${WORKSPACE_ID}/documents?page=1&page_size=50`;
const SECOND_PAGE_PATH = `/workspaces/${WORKSPACE_ID}/documents?page=2&page_size=50`;

function withStatuses(...statuses: DocumentStatus[]): DocumentOut[] {
  return statuses.map((status, index) =>
    status === "ready"
      ? readyDocumentFixture(index + 1)
      : documentFixture(index + 1, {
          status,
          error_code: status === "failed" ? "no_text" : null,
          can_retry: status === "failed",
        }),
  );
}

/** The list under its heading, as the workspace page shows it. */
function ListUnderHeading() {
  const headingRef = useRef<HTMLHeadingElement>(null);
  return (
    <>
      <h2 ref={headingRef} tabIndex={-1}>
        Documents
      </h2>
      <DocumentList workspaceId={WORKSPACE_ID} headingRef={headingRef} />
    </>
  );
}

function renderList(locale: Locale = "en") {
  return renderWithIntl(<ListUnderHeading />, { locale });
}

/**
 * Answers like the API would, keeping what a retry or a delete changes; `answer` can stand in
 * for those two, for example to fail them.
 */
function serve(
  initial: DocumentOut[],
  answer: { retry?: () => Promise<unknown>; delete?: () => Promise<unknown> } = {},
) {
  let documents = initial;
  apiFetchMock.mockImplementation(async (path, init) => {
    const id = /^\/documents\/([^/]+)/.exec(path)?.[1];
    if (init?.method === "POST" && id !== undefined) {
      if (answer.retry) {
        return answer.retry();
      }
      documents = documents.map((document) =>
        document.id === id
          ? { ...document, status: "uploaded", error_code: null, can_retry: false }
          : document,
      );
      return documents.find((document) => document.id === id);
    }
    if (init?.method === "DELETE" && id !== undefined) {
      if (answer.delete) {
        return answer.delete();
      }
      documents = documents.filter((document) => document.id !== id);
      return undefined;
    }
    return documentPageFixture(documents);
  });
}

function sent(method: string): unknown[][] {
  return apiFetchMock.mock.calls.filter(([, init]) => init?.method === method);
}

function rowNames(): string[] {
  const list = screen.getByRole("list", { name: "Documents in this workspace" });
  return within(list)
    .getAllByRole("link")
    .map((link) => link.textContent ?? "");
}

async function expectSummary(text: string): Promise<void> {
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(text));
}

describe("DocumentList", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("shows that the documents are loading, with the live region already in place", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderList();

    expect(screen.getByText("Loading documents…")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("lists the workspace's documents, the newest first", async () => {
    apiFetchMock.mockResolvedValue(
      documentPageFixture([
        readyDocumentFixture(1, { title: "Reaction mechanisms" }),
        documentFixture(2, { original_filename: "lecture-2.pdf", status: "processing" }),
      ]),
    );
    renderList();

    await screen.findByRole("link", { name: "Reaction mechanisms" });
    expect(apiFetchMock).toHaveBeenCalledWith(FIRST_PAGE_PATH);
    expect(rowNames()).toEqual(["Reaction mechanisms", "lecture-2.pdf"]);
  });

  it("says that there are no documents yet", async () => {
    apiFetchMock.mockResolvedValue(documentPageFixture([]));
    renderList();

    await expectSummary("No documents yet.");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it.each([
    [withStatuses("processing", "uploaded", "ready", "ready", "ready"), "Processing 2 of 5 files."],
    [withStatuses("ready", "ready", "ready", "ready", "ready"), "All 5 files are ready."],
    [
      withStatuses("failed", "ready", "ready", "ready", "ready"),
      "4 of 5 files are ready. 1 file failed.",
    ],
    [
      withStatuses("processing", "indexing", "failed", "ready", "ready"),
      "Processing 2 of 5 files. 1 file failed.",
    ],
    [withStatuses("failed", "ready"), "1 of 2 files is ready. 1 file failed."],
    [withStatuses("failed", "failed", "failed"), "3 files failed."],
    [withStatuses("ready"), "The file is ready."],
    [withStatuses("indexing"), "Processing the file."],
  ])("sums the list up in one polite live region: %#", async (documents, summary) => {
    apiFetchMock.mockResolvedValue(documentPageFixture(documents));
    renderList();

    await expectSummary(summary);
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it.each([
    [
      withStatuses("processing", "uploaded", "ready", "ready", "ready"),
      "В обработке 2 из 5 файлов.",
    ],
    [
      withStatuses("processing", ...Array<DocumentStatus>(20).fill("ready")),
      "В обработке 1 из 21 файла.",
    ],
    [withStatuses(...Array<DocumentStatus>(21).fill("ready")), "Все 21 файл готовы."],
    [withStatuses("ready", "ready", "ready"), "Все 3 файла готовы."],
    [
      withStatuses("failed", "ready", "ready", "ready", "ready"),
      "Готово 4 из 5 файлов. Не удалось обработать 1 файл.",
    ],
    [withStatuses("failed", "failed"), "Не удалось обработать 2 файла."],
    [withStatuses("ready"), "Файл готов."],
    [withStatuses("processing"), "Файл обрабатывается."],
  ])("sums the list up in Russian: %#", async (documents, summary) => {
    apiFetchMock.mockResolvedValue(documentPageFixture(documents));
    renderList("ru");

    await expectSummary(summary);
  });

  it.each([
    ["en", "ready", "Showing 50 of 51 files. All 50 files are ready."],
    ["en", "processing", "Showing 50 of 51 files. Processing 1 of 50 files."],
    ["en", "failed", "Showing 50 of 51 files. 49 of 50 files are ready. 1 file failed."],
    ["ru", "ready", "Показано 50 из 51 файла. Все 50 файлов готовы."],
    [
      "ru",
      "failed",
      "Показано 50 из 51 файла. Готово 49 из 50 файлов. Не удалось обработать 1 файл.",
    ],
  ] as const)(
    "counts only the documents loaded so far, and says so (%s, %s)",
    async (locale, firstStatus, summary) => {
      // The document not loaded yet may be ready, on its way or failed: nothing is said of it.
      const firstFifty = withStatuses(firstStatus, ...Array<DocumentStatus>(49).fill("ready"));
      apiFetchMock.mockResolvedValue(documentPageFixture(firstFifty, { total: 51 }));
      renderList(locale);

      await waitFor(() => expect(screen.getByRole("status").textContent).toBe(summary));
    },
  );

  it("updates the summary as documents finish", async () => {
    apiFetchMock
      .mockResolvedValueOnce(documentPageFixture(withStatuses("processing", "ready")))
      .mockResolvedValue(documentPageFixture(withStatuses("ready", "ready")));
    const { queryClient } = renderList();
    await expectSummary("Processing 1 of 2 files.");

    await act(() =>
      queryClient.refetchQueries({ queryKey: queryKeys.workspaceDocuments(WORKSPACE_ID) }),
    );

    await expectSummary("All 2 files are ready.");
  });

  it("loads the next page on Show more and moves focus to the first new document", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => readyDocumentFixture(index + 1));
    apiFetchMock
      .mockResolvedValueOnce(documentPageFixture(firstFifty, { total: 51 }))
      .mockResolvedValueOnce(
        documentPageFixture([readyDocumentFixture(51)], { page: 2, total: 51 }),
      );
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    const added = await screen.findByRole("link", { name: "Lecture 51" });
    expect(apiFetchMock).toHaveBeenLastCalledWith(SECOND_PAGE_PATH);
    expect(rowNames()).toHaveLength(51);
    await waitFor(() => expect(added).toHaveFocus());
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
    await expectSummary("All 51 files are ready.");
  });

  it("keeps the rows when the next page fails, and loads it on another try", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => readyDocumentFixture(index + 1));
    apiFetchMock
      .mockResolvedValueOnce(documentPageFixture(firstFifty, { total: 51 }))
      .mockRejectedValueOnce(new ApiError({ status: 503, code: "http_error", message: "x" }))
      .mockResolvedValueOnce(
        documentPageFixture([readyDocumentFixture(51)], { page: 2, total: 51 }),
      );
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "More documents could not be loaded.",
    );
    expect(rowNames()).toHaveLength(50);

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));

    expect(await screen.findByRole("link", { name: "Lecture 51" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports a failure to load and loads again on request", async () => {
    apiFetchMock
      .mockRejectedValueOnce(new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }))
      .mockResolvedValueOnce(documentPageFixture(withStatuses("ready")));
    renderList();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The API could not be reached. Check your connection and try again.",
    );
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.getByRole("button", { name: "Try again" })).toHaveAttribute(
      "data-variant",
      "secondary",
    );

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("link", { name: "Lecture 1" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // Try again had the focus and the rows took its place.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Documents" })).toHaveFocus());
  });

  it("names a server failure without its English message", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
    );
    renderList();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The documents could not be loaded.",
    );
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
  });

  it("drops rows it can no longer refresh once a request is refused", async () => {
    apiFetchMock
      .mockResolvedValueOnce(documentPageFixture(withStatuses("processing")))
      .mockRejectedValue(new ApiError({ status: 404, code: "workspace_not_found", message: "x" }));
    const { queryClient } = renderList();
    await screen.findByRole("link", { name: "lecture-1.pdf" });

    await act(() =>
      queryClient.refetchQueries({ queryKey: queryKeys.workspaceDocuments(WORKSPACE_ID) }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("This workspace no longer exists.");
    expect(screen.queryByRole("link", { name: "lecture-1.pdf" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("keeps the rows quietly when a refresh fails for a passing reason", async () => {
    apiFetchMock
      .mockResolvedValueOnce(documentPageFixture(withStatuses("processing")))
      .mockRejectedValue(new ApiError({ status: 503, code: "http_error", message: "x" }));
    const { queryClient } = renderList();
    await screen.findByRole("link", { name: "lecture-1.pdf" });

    await act(() =>
      queryClient.refetchQueries({ queryKey: queryKeys.workspaceDocuments(WORKSPACE_ID) }),
    );

    await waitFor(() =>
      expect(queryClient.getQueryState(queryKeys.workspaceDocuments(WORKSPACE_ID))?.status).toBe(
        "error",
      ),
    );
    expect(screen.getByRole("link", { name: "lecture-1.pdf" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Processing the file.");
  });

  it("speaks Russian", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => readyDocumentFixture(index + 1));
    apiFetchMock.mockResolvedValue(documentPageFixture(firstFifty, { total: 51 }));
    renderList("ru");

    expect(await screen.findByRole("button", { name: "Показать ещё" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Документы пространства" })).toBeInTheDocument();
  });
});

describe("DocumentList retry and delete", () => {
  const failed = documentFixture(1, {
    status: "failed",
    error_code: "pdf_unreadable",
    can_retry: true,
  });
  const ready = readyDocumentFixture(2, { title: "Reaction mechanisms" });

  function rowOf(name: string): HTMLElement {
    const row = screen.getByRole("link", { name }).closest("li");
    if (!row) {
      throw new Error(`No row for ${name}.`);
    }
    return row;
  }

  async function confirmDelete(filename: string): Promise<HTMLElement> {
    await userEvent.click(await screen.findByRole("button", { name: `Delete ${filename}` }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete this document?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete document" }));
    return dialog;
  }

  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("retries a failed document: its row moves on and focus goes to its title", async () => {
    serve([failed, ready]);
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "Retry lecture-1.pdf" }));

    expect(await within(rowOf("lecture-1.pdf")).findByText("In the queue")).toBeInTheDocument();
    expect(apiFetchMock).toHaveBeenCalledWith(`/documents/${failed.id}/retry`, {
      method: "POST",
    });
    expect(screen.queryByRole("button", { name: "Retry lecture-1.pdf" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("The PDF could not be read. The file may be damaged."),
    ).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("link", { name: "lecture-1.pdf" })).toHaveFocus());
    await expectSummary("Processing 1 of 2 files.");
  });

  it("shows Retry busy while the request runs and sends it once", async () => {
    serve([failed], { retry: () => new Promise(() => {}) });
    renderList();
    const retry = await screen.findByRole("button", { name: "Retry lecture-1.pdf" });

    await userEvent.click(retry);
    await userEvent.click(retry);

    expect(retry).toHaveAttribute("aria-busy", "true");
    expect(sent("POST")).toHaveLength(1);
  });

  it("says why a retry was refused and keeps Retry on offer", async () => {
    serve([failed], {
      retry: () =>
        Promise.reject(
          new ApiError({ status: 429, code: "rate_limited", message: "x", retryAfterSeconds: 120 }),
        ),
    });
    renderList();
    const retry = await screen.findByRole("button", { name: "Retry lecture-1.pdf" });

    await userEvent.click(retry);

    expect(await within(rowOf("lecture-1.pdf")).findByRole("alert")).toHaveTextContent(
      "Too many attempts. Try again in 2 minutes.",
    );
    expect(retry).toBeInTheDocument();
    expect(retry).toHaveFocus();
  });

  it("keeps the focus on the row when a retry is refused because processing is under way", async () => {
    let documents = [failed, ready];
    apiFetchMock.mockImplementation(async (_path, init) => {
      if (init?.method === "POST") {
        // Retried elsewhere a moment earlier.
        documents = [
          { ...failed, status: "processing", error_code: null, can_retry: false },
          ready,
        ];
        throw new ApiError({ status: 409, code: "document_not_retryable", message: "x" });
      }
      return documentPageFixture(documents);
    });
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "Retry lecture-1.pdf" }));

    expect(
      await within(rowOf("lecture-1.pdf")).findByText("Reading and analysing"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry lecture-1.pdf" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("link", { name: "lecture-1.pdf" })).toHaveFocus());
  });

  it("moves the focus to the list's heading when the document to retry is gone", async () => {
    let documents = [failed, ready];
    apiFetchMock.mockImplementation(async (_path, init) => {
      if (init?.method === "POST") {
        // Deleted elsewhere a moment earlier.
        documents = [ready];
        throw new ApiError({ status: 404, code: "document_not_found", message: "x" });
      }
      return documentPageFixture(documents);
    });
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "Retry lecture-1.pdf" }));

    await waitFor(() => expect(rowNames()).toEqual(["Reaction mechanisms"]));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Documents" })).toHaveFocus());
  });

  it("retries a stalled document", async () => {
    serve([documentFixture(1, { status: "processing", can_retry: true })]);
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "Retry lecture-1.pdf" }));

    expect(await screen.findByText("In the queue")).toBeInTheDocument();
    expect(screen.queryByText("This is taking longer than usual.")).not.toBeInTheDocument();
  });

  it("refreshes the workspace and the document's own data after a retry", async () => {
    serve([failed]);
    const { queryClient } = renderList();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await userEvent.click(await screen.findByRole("button", { name: "Retry lecture-1.pdf" }));

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["workspaces"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["documents", failed.id] });
  });

  it("deletes a document after asking, then moves focus to the list heading", async () => {
    serve([failed, ready]);
    renderList();

    await confirmDelete("lecture-2.pdf");

    // Hidden ones count too: the open dialog hides the page from assistive technology.
    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: "Reaction mechanisms", hidden: true }),
      ).not.toBeInTheDocument(),
    );
    expect(apiFetchMock).toHaveBeenCalledWith(`/documents/${ready.id}`, { method: "DELETE" });
    await waitFor(() => expect(screen.getByRole("heading", { name: "Documents" })).toHaveFocus());
    expect(rowNames()).toEqual(["lecture-1.pdf"]);
    await expectSummary("1 file failed.");
  });

  it("returns focus to the delete button when the question is dismissed", async () => {
    serve([ready]);
    renderList();
    const remove = await screen.findByRole("button", { name: "Delete lecture-2.pdf" });
    await userEvent.click(remove);
    await screen.findByRole("alertdialog");

    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(remove).toHaveFocus());
    expect(sent("DELETE")).toHaveLength(0);
  });

  it("keeps the question open with a translated error when the delete fails", async () => {
    serve([ready], {
      delete: () =>
        Promise.reject(
          new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
        ),
    });
    renderList();

    const dialog = await confirmDelete("lecture-2.pdf");

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The document could not be deleted. Try again.",
    );
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
    // The open dialog hides the page from assistive technology, so the row counts as hidden.
    expect(
      screen.getByRole("link", { name: "Reaction mechanisms", hidden: true }),
    ).toBeInTheDocument();
  });

  it("treats a document deleted elsewhere as deleted", async () => {
    let deleted = false;
    apiFetchMock.mockImplementation(async (_path, init) => {
      if (init?.method === "DELETE") {
        deleted = true;
        throw new ApiError({ status: 404, code: "document_not_found", message: "x" });
      }
      return documentPageFixture(deleted ? [] : [ready]);
    });
    renderList();

    await confirmDelete("lecture-2.pdf");

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("heading", { name: "Documents" })).toHaveFocus());
    await expectSummary("No documents yet.");
  });

  it("forgets the deleted document's own data and refreshes the workspace", async () => {
    serve([ready]);
    const { queryClient } = renderList();
    queryClient.setQueryData(queryKeys.document(ready.id), ready);
    queryClient.setQueryData(queryKeys.documentChunks(ready.id), { pages: [], pageParams: [] });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await confirmDelete("lecture-2.pdf");

    await waitFor(() =>
      expect(queryClient.getQueryData(queryKeys.document(ready.id))).toBeUndefined(),
    );
    expect(queryClient.getQueryData(queryKeys.documentChunks(ready.id))).toBeUndefined();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["workspaces"] });
  });
});
