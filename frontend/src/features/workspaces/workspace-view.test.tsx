import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { documentPageFixture, readyDocumentFixture } from "@/features/documents/test-fixtures";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { DocumentOut, WorkspaceOut, WorkspaceUpdateRequest } from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";
import { renderWithIntl } from "@/test/render";

import { workspaceFixture } from "./test-fixtures";
import { WorkspaceView } from "./workspace-view";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

const apiFetchMock = vi.mocked(apiFetch);

function isDocumentsPath(path: string): boolean {
  return path.includes("/documents");
}

const WORKSPACE = workspaceFixture(1, {
  name: "Organic chemistry",
  description: "Midterm on reaction mechanisms",
  exam_date: "2026-10-28",
  stats: { document_count: 5, ready_count: 5 },
});

// The API spells ids in lowercase; an address typed by hand may not.
const LETTERED = { ...WORKSPACE, id: "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d" };
const CAPITALISED_ID = LETTERED.id.toUpperCase();

function renderView(id = WORKSPACE.id, locale: Locale = "en") {
  return renderWithIntl(<WorkspaceView id={id} />, { locale });
}

/** Answers like the API would, keeping the changes a PATCH makes. */
function serve(workspace: WorkspaceOut, documents: DocumentOut[] = []) {
  let current = workspace;
  apiFetchMock.mockImplementation(async (path, init) => {
    if (isDocumentsPath(path)) {
      return documentPageFixture(documents);
    }
    if (init?.method === "PATCH") {
      current = { ...current, ...(init.json as WorkspaceUpdateRequest) };
    }
    return current;
  });
}

function primaryActions(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-variant="primary"]')).map(
    (element) => element.textContent ?? "",
  );
}

describe("WorkspaceView", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    replace.mockClear();
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 16, 12, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows that the workspace is loading under the page's one heading", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderView();

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByText("Loading the workspace…")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("asks for the workspace the address names", async () => {
    serve(WORKSPACE);
    renderView();

    await screen.findByRole("heading", { level: 1, name: "Organic chemistry" });
    expect(apiFetchMock).toHaveBeenCalledWith(`/workspaces/${WORKSPACE.id}`);
  });

  it("keeps an odd id inside its own path segment", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 422, code: "validation_error", message: "x" }),
    );
    renderView("../auth/me");

    await screen.findByRole("heading", { level: 1, name: "Workspace not found" });
    expect(apiFetchMock).toHaveBeenCalledWith("/workspaces/..%2Fauth%2Fme");
  });

  it("shows the workspace with the days to its exam in the margin", async () => {
    serve(WORKSPACE);
    renderView();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Organic chemistry" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByText("Midterm on reaction mechanisms")).toBeInTheDocument();
    const countdown = screen.getByText("Exam in 12 days");
    expect(countdown.closest("p")).toHaveClass("margin-note");
    expect(screen.getByText("October 28, 2026")).toHaveAttribute("dateTime", "2026-10-28");
  });

  it("counts the documents in the margin when no exam date is set", async () => {
    serve({ ...WORKSPACE, exam_date: null });
    renderView();

    await screen.findByRole("heading", { level: 1, name: "Organic chemistry" });
    expect(screen.queryByText(/Exam/)).not.toBeInTheDocument();
    const margin = document.querySelector(".margin-note");
    expect(margin).toHaveTextContent("5 documents");
  });

  it("lists the workspace's documents in their region, with no primary action of its own", async () => {
    serve(WORKSPACE, [readyDocumentFixture(1, { title: "Reaction mechanisms" })]);
    renderView();

    const region = await screen.findByRole("region", { name: "Documents" });
    expect(
      await within(region).findByRole("link", { name: "Reaction mechanisms" }),
    ).toBeInTheDocument();
    expect(within(region).getByRole("status")).toHaveTextContent("The file is ready.");
    expect(primaryActions()).toEqual([]);
  });

  it("moves focus to the documents heading once a document is deleted", async () => {
    let documents = [readyDocumentFixture(1, { title: "Reaction mechanisms" })];
    apiFetchMock.mockImplementation(async (path, init) => {
      if (init?.method === "DELETE") {
        documents = [];
        return undefined;
      }
      return isDocumentsPath(path) ? documentPageFixture(documents) : WORKSPACE;
    });
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Delete lecture-1.pdf" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete this document?" });

    await userEvent.click(within(dialog).getByRole("button", { name: "Delete document" }));

    const heading = screen.getByRole("heading", { level: 2, name: "Documents", hidden: true });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("heading", { level: 1, name: "Organic chemistry" })).toBeVisible();
  });

  it("asks for the documents by the id the API spells, whatever the address", async () => {
    serve(LETTERED);
    renderView(CAPITALISED_ID);

    const region = await screen.findByRole("region", { name: "Documents" });
    await waitFor(() =>
      expect(within(region).getByRole("status")).toHaveTextContent("No documents yet."),
    );
    expect(apiFetchMock).toHaveBeenCalledWith(
      `/workspaces/${LETTERED.id}/documents?page=1&page_size=50`,
    );
  });

  it("says a workspace that does not exist was not found", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "workspace_not_found", message: "Not found." }),
    );
    renderView();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Workspace not found" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("It may have been deleted, or the link is incomplete."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All workspaces" })).toHaveAttribute(
      "href",
      "/workspaces",
    );
    expect(primaryActions()).toEqual(["All workspaces"]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Not found.")).not.toBeInTheDocument();
  });

  it("treats an address that is no workspace id as not found", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 422, code: "validation_error", message: "x" }),
    );
    renderView("not-a-uuid");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Workspace not found" }),
    ).toBeInTheDocument();
  });

  it("reports any other failure and loads again on request", async () => {
    serve(WORKSPACE);
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
      await screen.findByRole("heading", { level: 1, name: "Organic chemistry" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names a server failure without its English message", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
    );
    renderView();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This workspace could not be loaded.",
    );
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
  });

  it("shows the new name once the changes are saved", async () => {
    serve(WORKSPACE);
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry II");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Organic chemistry II" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Edit workspace" })).not.toBeInTheDocument();
  });

  it("shows the saved name at once on an address that spells the id in capitals", async () => {
    let loaded = false;
    apiFetchMock.mockImplementation((path, init) => {
      if (isDocumentsPath(path)) {
        return Promise.resolve(documentPageFixture([]));
      }
      if (init?.method === "PATCH") {
        return Promise.resolve({ ...LETTERED, ...(init.json as WorkspaceUpdateRequest) });
      }
      if (loaded) {
        // The refresh after saving never lands, so only the saved workspace can change the page.
        return new Promise(() => {});
      }
      loaded = true;
      return Promise.resolve(LETTERED);
    });
    renderView(CAPITALISED_ID);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry II");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Organic chemistry II" }),
    ).toBeInTheDocument();
  });

  it("forgets a workspace deleted on an address that spells its id in capitals", async () => {
    apiFetchMock.mockImplementation((path, init) => {
      if (isDocumentsPath(path)) {
        return Promise.resolve(documentPageFixture([]));
      }
      return Promise.resolve(init?.method === "DELETE" ? undefined : LETTERED);
    });
    renderView(CAPITALISED_ID);
    await userEvent.click(await screen.findByRole("button", { name: "Delete workspace" }));
    const dialog = await screen.findByRole("alertdialog");

    await userEvent.click(within(dialog).getByRole("button", { name: "Delete workspace" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspaces"));
    // The load and the delete only: the page's copy is dropped, not fetched again to a 404.
    const workspaceRequests = apiFetchMock.mock.calls.filter(([path]) => !isDocumentsPath(path));
    expect(workspaceRequests).toHaveLength(2);
  });

  it("turns into not found once the workspace is gone, though a copy is cached", async () => {
    serve(WORKSPACE);
    const { queryClient } = renderView();
    await screen.findByRole("heading", { level: 1, name: "Organic chemistry" });

    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "workspace_not_found", message: "x" }),
    );
    await act(() => queryClient.refetchQueries({ queryKey: queryKeys.workspace(WORKSPACE.id) }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Workspace not found" }),
    ).toBeInTheDocument();
  });

  it("turns into not found when saving finds the workspace deleted elsewhere", async () => {
    serve(WORKSPACE);
    renderView();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "workspace_not_found", message: "x" }),
    );

    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Organic chemistry II");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Workspace not found" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete workspace" })).not.toBeInTheDocument();
  });

  it("keeps showing the workspace when a later refresh fails for another reason", async () => {
    serve(WORKSPACE);
    const { queryClient } = renderView();
    await screen.findByRole("heading", { level: 1, name: "Organic chemistry" });

    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }),
    );
    await act(() => queryClient.refetchQueries({ queryKey: queryKeys.workspace(WORKSPACE.id) }));

    await waitFor(() =>
      expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE.id))?.status).toBe("error"),
    );
    expect(screen.getByRole("heading", { level: 1, name: "Organic chemistry" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("speaks Russian", async () => {
    serve(WORKSPACE);
    renderView(WORKSPACE.id, "ru");

    const region = await screen.findByRole("region", { name: "Документы" });
    await waitFor(() =>
      expect(within(region).getByRole("status")).toHaveTextContent("Документов пока нет."),
    );
    expect(screen.getByText("Экзамен через 12 дней")).toBeInTheDocument();
    expect(screen.getByText("28 октября 2026 г.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Изменить" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Удалить пространство" })).toBeInTheDocument();
  });

  it("counts documents in the margin in Russian", async () => {
    serve({ ...WORKSPACE, exam_date: null, stats: { ...WORKSPACE.stats, document_count: 3 } });
    renderView(WORKSPACE.id, "ru");

    await screen.findByRole("heading", { level: 1, name: "Organic chemistry" });
    expect(document.querySelector(".margin-note")).toHaveTextContent("3 документа");
  });

  it("is loading and not found in Russian", async () => {
    apiFetchMock.mockReturnValueOnce(new Promise(() => {}));
    const { unmount } = renderView(WORKSPACE.id, "ru");
    expect(screen.getByRole("heading", { level: 1, name: "Пространство" })).toBeInTheDocument();
    expect(screen.getByText("Загрузка пространства…")).toBeInTheDocument();
    unmount();

    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "workspace_not_found", message: "x" }),
    );
    renderView(WORKSPACE.id, "ru");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Пространство не найдено" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Все пространства" })).toBeInTheDocument();
  });
});
