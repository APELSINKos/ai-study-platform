import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { workspaceFixture, workspacePageFixture } from "@/features/workspaces/test-fixtures";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { RecentWorkspaces } from "./recent-workspaces";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

function primaryActions(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-variant="primary"]')).map(
    (element) => element.textContent ?? "",
  );
}

describe("RecentWorkspaces", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("asks only for the three most recently changed workspaces", async () => {
    apiFetchMock.mockResolvedValueOnce(
      workspacePageFixture([workspaceFixture(1)], { pageSize: 3 }),
    );
    renderWithIntl(<RecentWorkspaces />);

    await screen.findByRole("link", { name: "Workspace 1" });
    expect(apiFetchMock).toHaveBeenCalledWith("/workspaces?page=1&page_size=3");
  });

  it("says it is loading and offers nothing to press yet", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<RecentWorkspaces />);

    expect(screen.getByText("Loading workspaces…")).toBeInTheDocument();
    expect(primaryActions()).toEqual([]);
  });

  it("invites the first workspace with the dashboard's one primary action", async () => {
    apiFetchMock.mockResolvedValueOnce(workspacePageFixture([], { pageSize: 3 }));
    renderWithIntl(<RecentWorkspaces />);

    const action = await screen.findByRole("link", { name: "New workspace" });
    expect(action).toHaveAttribute("href", "/workspaces?new=1");
    expect(primaryActions()).toEqual(["New workspace"]);
    expect(screen.getByRole("heading", { name: "Start with a workspace" })).toBeInTheDocument();
  });

  it("lists the recent workspaces with a way to all of them, and no primary action", async () => {
    apiFetchMock.mockResolvedValueOnce(
      workspacePageFixture(
        [
          workspaceFixture(1, { name: "Organic chemistry" }),
          workspaceFixture(2, { name: "Linear algebra" }),
          workspaceFixture(3, { name: "Statistics" }),
        ],
        { pageSize: 3, total: 8 },
      ),
    );
    renderWithIntl(<RecentWorkspaces />);

    const section = await screen.findByRole("region", { name: "Recent workspaces" });
    const rows = within(section).getAllByRole("listitem");
    expect(rows.map((row) => within(row).getByRole("link").textContent)).toEqual([
      "Organic chemistry",
      "Linear algebra",
      "Statistics",
    ]);
    expect(within(section).getByRole("link", { name: "All workspaces" })).toHaveAttribute(
      "href",
      "/workspaces",
    );
    expect(primaryActions()).toEqual([]);
  });

  it("reports a failure to load and loads again on request", async () => {
    apiFetchMock
      .mockRejectedValueOnce(new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" }))
      .mockResolvedValueOnce(workspacePageFixture([workspaceFixture(1)], { pageSize: 3 }));
    renderWithIntl(<RecentWorkspaces />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The API could not be reached. Check your connection and try again.",
    );

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("link", { name: "Workspace 1" })).toBeInTheDocument();
    // Try again had the focus and the card took its place.
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Recent workspaces" })).toHaveFocus(),
    );
  });

  it("puts the focus on the invitation when Try again finds no workspaces", async () => {
    apiFetchMock
      .mockRejectedValueOnce(new ApiError({ status: 503, code: "http_error", message: "x" }))
      .mockResolvedValueOnce(workspacePageFixture([], { pageSize: 3 }));
    renderWithIntl(<RecentWorkspaces />);

    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));

    const heading = await screen.findByRole("heading", { name: "Start with a workspace" });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it("speaks Russian", async () => {
    apiFetchMock.mockResolvedValueOnce(
      workspacePageFixture([workspaceFixture(1)], { pageSize: 3 }),
    );
    renderWithIntl(<RecentWorkspaces />, { locale: "ru" });

    expect(
      await screen.findByRole("region", { name: "Недавние пространства" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Все пространства" })).toBeInTheDocument();
  });

  it("invites the first workspace in Russian", async () => {
    apiFetchMock.mockResolvedValueOnce(workspacePageFixture([], { pageSize: 3 }));
    renderWithIntl(<RecentWorkspaces />, { locale: "ru" });

    expect(await screen.findByRole("link", { name: "Новое пространство" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Начните с пространства" })).toBeInTheDocument();
  });
});
