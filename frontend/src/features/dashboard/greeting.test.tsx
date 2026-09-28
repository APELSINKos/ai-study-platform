import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/render";

import { DashboardGreeting } from "./greeting";

const fetchMock = vi.fn<typeof fetch>();

describe("DashboardGreeting", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a quiet placeholder while the account is pending, with a hidden heading", () => {
    fetchMock.mockImplementation(() => new Promise(() => {}));
    renderWithIntl(<DashboardGreeting />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("greets the signed-in user by name", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "11111111-1111-1111-1111-111111111111",
          email: "ada@example.com",
          display_name: "Ada Lovelace",
          created_at: "2024-01-01T00:00:00Z",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    renderWithIntl(<DashboardGreeting />);

    expect(
      await screen.findByRole("heading", { name: "Hello, Ada Lovelace." }),
    ).toBeInTheDocument();
  });
});
