import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { WorkspaceOut } from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";
import { renderWithIntl } from "@/test/render";

import { useRecentWorkspaces } from "./hooks";
import { workspaceFixture, workspacePageFixture } from "./test-fixtures";
import { WorkspaceHeader } from "./workspace-header";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

const apiFetchMock = vi.mocked(apiFetch);

const WORKSPACE = workspaceFixture(1, {
  name: "Organic chemistry",
  description: "Midterm: chapters 1 to 6\nLab safety briefing",
  stats: { document_count: 5, ready_count: 5 },
});
const WORKSPACE_PATH = `/workspaces/${WORKSPACE.id}`;

const OTHER = workspaceFixture(2, { name: "Linear algebra" });

function renderHeader(workspace: WorkspaceOut = WORKSPACE, locale: Locale = "en") {
  const view = renderWithIntl(<WorkspaceHeader workspace={workspace} />, { locale });
  const { queryClient } = view;
  // What the app has cached by now: the workspace with its documents, the lists it came from
  // and another workspace opened earlier.
  queryClient.setQueryData(queryKeys.workspace(workspace.id), workspace);
  queryClient.setQueryData(queryKeys.workspaceDocuments(workspace.id), { pages: [] });
  queryClient.setQueryData(queryKeys.workspaceList, {
    pages: [workspacePageFixture([workspace, OTHER])],
    pageParams: [1],
  });
  queryClient.setQueryData(queryKeys.recentWorkspaces, workspacePageFixture([workspace, OTHER]));
  queryClient.setQueryData(queryKeys.workspace(OTHER.id), OTHER);
  return view;
}

/** The dashboard's recent workspaces, as a page on screen shows them. */
function RecentWorkspaceNames() {
  const recent = useRecentWorkspaces();
  return (
    <ul aria-label="Recent">
      {recent.data?.items.map((workspace) => (
        <li key={workspace.id}>{workspace.name}</li>
      ))}
    </ul>
  );
}

function variantOf(name: string): string | undefined {
  return screen.getByRole("button", { name }).dataset.variant;
}

async function openDeleteDialog(): Promise<HTMLElement> {
  await userEvent.click(screen.getByRole("button", { name: "Delete workspace" }));
  return screen.findByRole("alertdialog", { name: "Delete this workspace?" });
}

function confirmDelete(dialog: HTMLElement): Promise<void> {
  return userEvent.click(within(dialog).getByRole("button", { name: "Delete workspace" }));
}

describe("WorkspaceHeader", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    replace.mockClear();
  });

  it("names the workspace in the page's one heading and keeps the description's lines", () => {
    renderHeader();

    expect(
      screen.getByRole("heading", { level: 1, name: "Organic chemistry" }),
    ).toBeInTheDocument();
    const description = screen.getByText(/Midterm: chapters 1 to 6/);
    expect(description.textContent).toBe("Midterm: chapters 1 to 6\nLab safety briefing");
    expect(description).toHaveClass("whitespace-pre-line");
  });

  it("renders the name and the description as plain text", () => {
    renderHeader(
      workspaceFixture(1, { name: "<img src=x onerror=alert(1)>", description: "<b>not bold</b>" }),
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "<img src=x onerror=alert(1)>" }),
    ).toBeInTheDocument();
    expect(screen.getByText("<b>not bold</b>")).toBeInTheDocument();
    expect(document.querySelector("img, b")).toBeNull();
  });

  it("offers Edit quietly and Delete workspace as a danger action, never a primary one", () => {
    renderHeader();

    expect(variantOf("Edit")).toBe("ghost");
    expect(variantOf("Delete workspace")).toBe("danger");
    expect(document.querySelector('[data-variant="primary"]')).toBeNull();
  });

  it("opens the edit form in place of the description and the actions", async () => {
    renderHeader();

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getByRole("form", { name: "Edit workspace" })).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.queryByText(/Midterm: chapters 1 to 6/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete workspace" })).not.toBeInTheDocument();
  });

  it("closes the form on Cancel and gives the focus back to Edit", async () => {
    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("form", { name: "Edit workspace" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toHaveFocus();
    expect(screen.getByText(/Midterm: chapters 1 to 6/)).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("closes the form once the changes are saved and gives the focus back to Edit", async () => {
    apiFetchMock.mockResolvedValue({ ...WORKSPACE, name: "Organic chemistry II" });
    renderHeader();
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));

    await userEvent.type(screen.getByLabelText("Name"), " II");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(screen.queryByRole("form", { name: "Edit workspace" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Edit" })).toHaveFocus();
    expect(apiFetchMock).toHaveBeenCalledWith(WORKSPACE_PATH, {
      method: "PATCH",
      json: { name: "Organic chemistry II" },
    });
  });

  it("asks before deleting and says what goes with the workspace", async () => {
    renderHeader();

    const dialog = await openDeleteDialog();

    expect(dialog).toHaveAccessibleDescription(
      "“Organic chemistry” and its 5 documents will be deleted. This cannot be undone.",
    );
    expect(within(dialog).getByRole("button", { name: "Delete workspace" })).toHaveAttribute(
      "data-variant",
      "danger",
    );
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [0, "“Organic chemistry” will be deleted. This cannot be undone."],
    [1, "“Organic chemistry” and its document will be deleted. This cannot be undone."],
  ])("counts %i document(s) in the question", async (count, expected) => {
    renderHeader({ ...WORKSPACE, stats: { ...WORKSPACE.stats, document_count: count } });

    expect(await openDeleteDialog()).toHaveAccessibleDescription(expected);
  });

  it("deletes the workspace, forgets it and goes back to the list", async () => {
    apiFetchMock.mockResolvedValue(undefined);
    const { queryClient } = renderHeader();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await confirmDelete(await openDeleteDialog());

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspaces"));
    expect(apiFetchMock).toHaveBeenCalledWith(WORKSPACE_PATH, { method: "DELETE" });
    expect(queryClient.getQueryData(queryKeys.workspace(WORKSPACE.id))).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.workspaceDocuments(WORKSPACE.id))).toBeUndefined();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["workspaces"] });
  });

  it("drops the cached lists, so the list it returns to never shows the deleted workspace", async () => {
    apiFetchMock.mockResolvedValue(undefined);
    const { queryClient } = renderHeader();

    await confirmDelete(await openDeleteDialog());

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspaces"));
    expect(queryClient.getQueryData(queryKeys.workspaceList)).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.recentWorkspaces)).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.workspace(OTHER.id))).toEqual(OTHER);
  });

  it("keeps the question open until the workspace is deleted", async () => {
    const deletion = Promise.withResolvers<undefined>();
    apiFetchMock.mockReturnValue(deletion.promise);
    renderHeader();
    const dialog = await openDeleteDialog();

    await confirmDelete(dialog);
    await userEvent.keyboard("{Escape}");

    expect(within(dialog).getByRole("button", { name: "Delete workspace" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();

    deletion.resolve(undefined);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspaces"));
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("leaves a user who has moved on where they went once the workspace is deleted", async () => {
    const deletion = Promise.withResolvers<undefined>();
    apiFetchMock.mockReturnValue(deletion.promise);
    const { queryClient, unmount } = renderHeader();
    await confirmDelete(await openDeleteDialog());
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));

    unmount();
    deletion.resolve(undefined);

    await waitFor(() =>
      expect(queryClient.getQueryData(queryKeys.workspace(WORKSPACE.id))).toBeUndefined(),
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("refreshes a list of workspaces that is on screen rather than dropping it", async () => {
    // The user went back to the dashboard while the workspace was being deleted.
    let deleted = false;
    apiFetchMock.mockImplementation((_path, init) => {
      if (init?.method === "DELETE") {
        deleted = true;
        return Promise.resolve(undefined);
      }
      return Promise.resolve(workspacePageFixture(deleted ? [OTHER] : [WORKSPACE, OTHER]));
    });
    renderWithIntl(
      <>
        <WorkspaceHeader workspace={WORKSPACE} />
        <RecentWorkspaceNames />
      </>,
    );
    const recent = screen.getByRole("list", { name: "Recent" });
    expect(await within(recent).findByText("Organic chemistry")).toBeInTheDocument();

    await confirmDelete(await openDeleteDialog());

    await waitFor(() =>
      expect(within(recent).queryByText("Organic chemistry")).not.toBeInTheDocument(),
    );
    expect(within(recent).getByText("Linear algebra")).toBeInTheDocument();
  });

  it("says why the workspace could not be deleted and stays on the page", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
    );
    const { queryClient } = renderHeader();
    const dialog = await openDeleteDialog();

    await confirmDelete(dialog);

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The workspace could not be deleted. Try again.",
    );
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(queryKeys.workspace(WORKSPACE.id))).toEqual(WORKSPACE);
  });

  it("leaves a workspace deleted elsewhere in the meantime as if it was deleted here", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 404, code: "workspace_not_found", message: "x" }),
    );
    const { queryClient } = renderHeader();

    await confirmDelete(await openDeleteDialog());

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspaces"));
    expect(queryClient.getQueryData(queryKeys.workspace(WORKSPACE.id))).toBeUndefined();
  });

  it("speaks Russian", async () => {
    renderHeader(WORKSPACE, "ru");

    expect(screen.getByRole("button", { name: "Изменить" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Удалить пространство" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Удалить это пространство?" });
    expect(dialog).toHaveAccessibleDescription(
      "Пространство «Organic chemistry» будет удалено вместе с 5 документами. Это нельзя отменить.",
    );
  });

  it.each([
    [
      1,
      "Пространство «Organic chemistry» будет удалено вместе с 1 документом. Это нельзя отменить.",
    ],
    [
      3,
      "Пространство «Organic chemistry» будет удалено вместе с 3 документами. Это нельзя отменить.",
    ],
    [0, "Пространство «Organic chemistry» будет удалено. Это нельзя отменить."],
  ])("counts %i document(s) in Russian", async (count, expected) => {
    renderHeader({ ...WORKSPACE, stats: { ...WORKSPACE.stats, document_count: count } }, "ru");

    await userEvent.click(screen.getByRole("button", { name: "Удалить пространство" }));

    expect(await screen.findByRole("alertdialog")).toHaveAccessibleDescription(expected);
  });
});
