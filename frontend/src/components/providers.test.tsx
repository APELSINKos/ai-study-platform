import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCurrentUser } from "@/features/auth/hooks";
import { emitSessionExpired } from "@/lib/api/session-events";

import { Providers } from "./providers";

const replace = vi.fn();
const navigation = { pathname: "/" };

vi.mock("next-themes", () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => navigation.pathname,
}));

const fetchMock = vi.fn<typeof fetch>();

function Probe() {
  useCurrentUser();
  return null;
}

function errorResponse(code: string, status: number): Response {
  return new Response(
    JSON.stringify({ error: { code, message: code, details: [], request_id: null } }),
    {
      status,
      headers: { "Content-Type": "application/json" },
    },
  );
}

function setPath(path: string): void {
  window.history.pushState({}, "", path);
  navigation.pathname = window.location.pathname;
}

function countCallsTo(path: string): number {
  return fetchMock.mock.calls.filter(([input]) => String(input).endsWith(path)).length;
}

describe("Providers", () => {
  beforeEach(() => {
    replace.mockClear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return errorResponse("invalid_refresh_token", 401);
      }
      return errorResponse("not_authenticated", 401);
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setPath("/");
  });

  it("redirects once from a protected path, without an unbounded retry loop", async () => {
    setPath("/dashboard?tab=progress");

    const { rerender } = render(
      <Providers>
        <Probe />
      </Providers>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalled());

    // A real router transition re-renders the still-mounted tree; simulate that here.
    rerender(
      <Providers>
        <Probe />
      </Providers>,
    );
    // The page asks for the user once more, and the session is found lost a second time.
    await waitFor(() => expect(countCallsTo("/auth/refresh")).toBe(2));

    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith(
      `/login?next=${encodeURIComponent("/dashboard?tab=progress")}`,
    );
    expect(countCallsTo("/auth/me")).toBe(2);
  });

  it("redirects again when a later session is lost after signing back in", async () => {
    setPath("/dashboard");
    const tree = () => (
      <Providers>
        <Probe />
      </Providers>
    );
    const { rerender } = render(tree());
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));

    // The redirect lands on the login page, then signing in leads back to the dashboard.
    setPath("/login");
    rerender(tree());
    setPath("/dashboard");
    rerender(tree());
    act(() => emitSessionExpired());

    expect(replace).toHaveBeenCalledTimes(2);
    expect(replace).toHaveBeenLastCalledWith(`/login?next=${encodeURIComponent("/dashboard")}`);
  });

  it("does nothing on the login page", async () => {
    setPath("/login");

    render(
      <Providers>
        <Probe />
      </Providers>,
    );

    // The session is found lost once the refresh is refused.
    await waitFor(() => expect(countCallsTo("/auth/refresh")).toBe(1));

    expect(replace).not.toHaveBeenCalled();
    expect(countCallsTo("/auth/me")).toBe(1);
  });

  it("does nothing on the landing page", async () => {
    setPath("/");

    render(
      <Providers>
        <Probe />
      </Providers>,
    );

    await waitFor(() => expect(countCallsTo("/auth/refresh")).toBe(1));

    expect(replace).not.toHaveBeenCalled();
    expect(countCallsTo("/auth/me")).toBe(1);
  });
});
