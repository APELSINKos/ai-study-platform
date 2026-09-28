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

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(menuButton).toHaveFocus();
  });
});
