import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/render";

import { AppShell } from "./app-shell";

const navigation = { pathname: "/dashboard" };

vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "light", setTheme: vi.fn() }) }));
vi.mock("@/i18n/actions", () => ({ setLocale: vi.fn(async () => undefined) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => navigation.pathname,
}));

const fetchMock = vi.fn<typeof fetch>();

function meResponse(): Response {
  return new Response(
    JSON.stringify({
      id: "11111111-1111-1111-1111-111111111111",
      email: "ada@example.com",
      display_name: "Ada Lovelace",
      created_at: "2024-01-01T00:00:00Z",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function meErrorResponse(status: number, code = "http_error"): Response {
  return new Response(
    JSON.stringify({ error: { code, message: "boom", details: [], request_id: null } }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    navigation.pathname = "/dashboard";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a quiet skeleton while the account is pending, no name or sign-out yet", () => {
    fetchMock.mockImplementation(() => new Promise(() => {}));
    renderWithIntl(
      <AppShell>
        <p>page content</p>
      </AppShell>,
    );

    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
    expect(screen.getByText("page content")).toBeInTheDocument();
  });

  it("renders the account and marks the current nav destination", async () => {
    fetchMock.mockResolvedValue(meResponse());
    renderWithIntl(
      <AppShell>
        <p>page content</p>
      </AppShell>,
    );

    await screen.findByText("Ada Lovelace");
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();

    const dashboardLink = screen.getByRole("link", { name: "Dashboard" });
    expect(dashboardLink).toHaveAttribute("aria-current", "page");
  });

  it("opens the mobile menu on click and closes it on Escape, returning focus", async () => {
    fetchMock.mockResolvedValue(meResponse());
    const user = userEvent.setup();
    renderWithIntl(
      <AppShell>
        <p>page content</p>
      </AppShell>,
    );
    await screen.findByText("Ada Lovelace");

    const menuButton = screen.getByRole("button", { name: "Open menu" });
    await user.click(menuButton);

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(dialog).toHaveAccessibleDescription("Main navigation and account");

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(menuButton).toHaveFocus();
  });

  it("shows an error state with a retry when the account fails to load with a 500", async () => {
    fetchMock.mockResolvedValue(meErrorResponse(500));
    renderWithIntl(
      <AppShell>
        <p>page content</p>
      </AppShell>,
    );

    expect(await screen.findByText("We couldn't load your account.")).toBeInTheDocument();
    expect(screen.queryByText("page content")).not.toBeInTheDocument();

    fetchMock.mockResolvedValue(meResponse());
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("page content")).toBeInTheDocument();
  });

  it("shows the error state when the account request fails outright", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    renderWithIntl(
      <AppShell>
        <p>page content</p>
      </AppShell>,
    );

    expect(await screen.findByText("We couldn't load your account.")).toBeInTheDocument();
  });

  it("does not flash the error state on a 401, since a redirect is already under way", async () => {
    fetchMock.mockResolvedValue(meErrorResponse(401, "not_authenticated"));
    renderWithIntl(
      <AppShell>
        <p>page content</p>
      </AppShell>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByText("We couldn't load your account.")).not.toBeInTheDocument();
    expect(screen.getByText("page content")).toBeInTheDocument();
  });
});
