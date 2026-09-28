import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks";
import type { UserOut } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { UserMenu } from "./user-menu";

const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const fetchMock = vi.fn<typeof fetch>();

const user: UserOut = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "ada@example.com",
  display_name: "Ada Lovelace",
  created_at: "2024-01-01T00:00:00Z",
};

function errorResponse(): Response {
  return new Response(
    JSON.stringify({
      error: { code: "http_error", message: "boom", details: [], request_id: null },
    }),
    { status: 500, headers: { "Content-Type": "application/json" } },
  );
}

describe("UserMenu", () => {
  beforeEach(() => {
    push.mockClear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a quiet placeholder while the account is unknown", () => {
    renderWithIntl(<UserMenu user={undefined} />);

    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("shows the display name and email", () => {
    renderWithIntl(<UserMenu user={user} />);

    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
  });

  it("signs out, clears the cache and navigates to login", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const { queryClient } = renderWithIntl(<UserMenu user={user} />);
    queryClient.setQueryData(CURRENT_USER_QUERY_KEY, user);

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
    expect(queryClient.getQueryData(CURRENT_USER_QUERY_KEY)).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/auth/logout"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows an error and stays put when sign-out fails", async () => {
    fetchMock.mockResolvedValue(errorResponse());
    renderWithIntl(<UserMenu user={user} />);

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not sign out. Try again.");
    expect(push).not.toHaveBeenCalled();
  });
});
