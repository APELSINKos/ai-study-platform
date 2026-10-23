import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { workspaceFixture, workspacePageFixture } from "./test-fixtures";
import { WorkspaceList } from "./workspace-list";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const apiFetchMock = vi.mocked(apiFetch);

const FIRST_PAGE_PATH = "/workspaces?page=1&page_size=20";
const SECOND_PAGE_PATH = "/workspaces?page=2&page_size=20";

function workspaces(from: number, to: number) {
  return Array.from({ length: to - from + 1 }, (_, offset) => workspaceFixture(from + offset));
}

function rowNames(): string[] {
  const list = screen.getByRole("list", { name: "Your workspaces" });
  return within(list)
    .getAllByRole("link")
    .map((link) => link.textContent ?? "");
}

function primaryButtons(): string[] {
  return screen
    .queryAllByRole("button")
    .filter((button) => button.dataset.variant === "primary")
    .map((button) => button.textContent ?? "");
}

describe("WorkspaceList", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("titles the page and shows that the list is loading", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<WorkspaceList />);

    expect(screen.getByRole("heading", { level: 1, name: "Workspaces" })).toBeInTheDocument();
    expect(screen.getByText("Loading workspaces…")).toBeInTheDocument();
    expect(screen.getByText("One for each course or exam.")).toBeInTheDocument();
  });

  it("lists the first page of workspaces, most recently updated first", async () => {
    apiFetchMock.mockResolvedValueOnce(
      workspacePageFixture([
        workspaceFixture(1, { name: "Organic chemistry" }),
        workspaceFixture(2, { name: "Linear algebra" }),
      ]),
    );
    renderWithIntl(<WorkspaceList />);

    await screen.findByRole("link", { name: "Organic chemistry" });
    expect(rowNames()).toEqual(["Organic chemistry", "Linear algebra"]);
    expect(apiFetchMock).toHaveBeenCalledWith(FIRST_PAGE_PATH);
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("loads the next page on Show more and moves focus to the first new workspace", async () => {
    apiFetchMock
      .mockResolvedValueOnce(workspacePageFixture(workspaces(1, 20), { total: 21 }))
      .mockResolvedValueOnce(workspacePageFixture(workspaces(21, 21), { page: 2, total: 21 }));
    renderWithIntl(<WorkspaceList />);

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    const added = await screen.findByRole("link", { name: "Workspace 21" });
    expect(apiFetchMock).toHaveBeenLastCalledWith(SECOND_PAGE_PATH);
    expect(rowNames()).toHaveLength(21);
    await waitFor(() => expect(added).toHaveFocus());
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("shows a workspace once when the pages shift under it", async () => {
    // A workspace updated meanwhile moves up, so the next page repeats one already shown.
    apiFetchMock
      .mockResolvedValueOnce(workspacePageFixture(workspaces(1, 20), { total: 22 }))
      .mockResolvedValueOnce(workspacePageFixture(workspaces(20, 21), { page: 2, total: 22 }));
    renderWithIntl(<WorkspaceList />);

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    await screen.findByRole("link", { name: "Workspace 21" });
    expect(screen.getAllByRole("link", { name: "Workspace 20" })).toHaveLength(1);
    expect(rowNames()).toHaveLength(21);
  });

  it("keeps the rows when the next page fails, and loads it on another try", async () => {
    apiFetchMock
      .mockResolvedValueOnce(workspacePageFixture(workspaces(1, 20), { total: 21 }))
      .mockRejectedValueOnce(new ApiError({ status: 503, code: "http_error", message: "x" }))
      .mockResolvedValueOnce(workspacePageFixture(workspaces(21, 21), { page: 2, total: 21 }));
    renderWithIntl(<WorkspaceList />);

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "More workspaces could not be loaded.",
    );
    expect(rowNames()).toHaveLength(20);

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));

    expect(await screen.findByRole("link", { name: "Workspace 21" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("opens the create form when there are no workspaces yet", async () => {
    apiFetchMock.mockResolvedValueOnce(workspacePageFixture([]));
    renderWithIntl(<WorkspaceList />);

    expect(await screen.findByRole("form", { name: "New workspace" })).toBeInTheDocument();
    expect(
      screen.getByText("You have no workspaces yet. Start with the course you are studying now."),
    ).toBeInTheDocument();
    expect(primaryButtons()).toEqual(["Create workspace"]);
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Your workspaces" })).not.toBeInTheDocument();
    // Arriving from the menu is not a request to type yet.
    expect(screen.getByLabelText("Name")).not.toHaveFocus();
  });

  it("offers one primary action, New workspace, above the list", async () => {
    apiFetchMock.mockResolvedValueOnce(workspacePageFixture([workspaceFixture(1)]));
    renderWithIntl(<WorkspaceList />);

    await screen.findByRole("link", { name: "Workspace 1" });

    expect(primaryButtons()).toEqual(["New workspace"]);
    expect(screen.queryByRole("form", { name: "New workspace" })).not.toBeInTheDocument();
  });

  it("opens the form in place of the button and returns focus to it on Cancel", async () => {
    apiFetchMock.mockResolvedValueOnce(workspacePageFixture([workspaceFixture(1)]));
    renderWithIntl(<WorkspaceList />);

    await userEvent.click(await screen.findByRole("button", { name: "New workspace" }));

    expect(screen.getByRole("form", { name: "New workspace" })).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(primaryButtons()).toEqual(["Create workspace"]);
    expect(rowNames()).toEqual(["Workspace 1"]);

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("form", { name: "New workspace" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New workspace" })).toHaveFocus();
  });

  it("starts with the form open when the page is asked for it", async () => {
    apiFetchMock.mockResolvedValueOnce(workspacePageFixture([workspaceFixture(1)]));
    renderWithIntl(<WorkspaceList startWithForm />);

    expect(screen.getByRole("form", { name: "New workspace" })).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveFocus();
    await screen.findByRole("link", { name: "Workspace 1" });
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New workspace" })).not.toBeInTheDocument();
  });

  it("offers no action while the list is still loading", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<WorkspaceList />);

    expect(primaryButtons()).toEqual([]);
  });

  it("reports a failure to load and loads again on request", async () => {
    apiFetchMock
      .mockRejectedValueOnce(new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }))
      .mockResolvedValueOnce(workspacePageFixture([workspaceFixture(1)]));
    renderWithIntl(<WorkspaceList />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The API could not be reached. Check your connection and try again.",
    );
    // A workspace can still be created while the list is unavailable.
    expect(primaryButtons()).toEqual(["New workspace"]);

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("link", { name: "Workspace 1" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // Try again had the focus and the rows took its place.
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: "Workspaces" })).toHaveFocus(),
    );
  });

  it("names a server failure without its English message", async () => {
    apiFetchMock.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "internal_error", message: "Internal server error." }),
    );
    renderWithIntl(<WorkspaceList />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your workspaces could not be loaded.",
    );
    expect(screen.queryByText("Internal server error.")).not.toBeInTheDocument();
  });

  it("speaks Russian", async () => {
    apiFetchMock.mockResolvedValueOnce(workspacePageFixture(workspaces(1, 20), { total: 21 }));
    renderWithIntl(<WorkspaceList />, { locale: "ru" });

    expect(await screen.findByRole("button", { name: "Показать ещё" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Пространства" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Ваши пространства" })).toBeInTheDocument();
  });
});
