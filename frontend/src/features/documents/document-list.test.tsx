import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type * as MotionModule from "motion/react";
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

function renderList(locale: Locale = "en") {
  return renderWithIntl(<DocumentList workspaceId={WORKSPACE_ID} />, { locale });
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
    ["en", "ready", "50 of 51 files are ready."],
    ["en", "processing", "Processing 1 of 51 files."],
    ["ru", "ready", "Готово 50 из 51 файла."],
  ] as const)(
    "counts the documents not loaded yet without vouching for them (%s, %s)",
    async (locale, firstStatus, summary) => {
      const firstFifty = withStatuses(firstStatus, ...Array<DocumentStatus>(49).fill("ready"));
      apiFetchMock.mockResolvedValue(documentPageFixture(firstFifty, { total: 51 }));
      renderList(locale);

      await expectSummary(summary);
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
