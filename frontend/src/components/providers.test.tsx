import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCurrentUser } from "@/features/auth/hooks";

import { Providers } from "./providers";

const replace = vi.fn();

vi.mock("next-themes", () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

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
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 20));
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
    await settle();

    // A real router transition re-renders the still-mounted tree; simulate that here.
    rerender(
      <Providers>
        <Probe />
      </Providers>,
    );
    await settle();

    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith(
      `/login?next=${encodeURIComponent("/dashboard?tab=progress")}`,
    );
    expect(countCallsTo("/auth/me")).toBeLessThanOrEqual(2);
  });

  it("does nothing on the login page", async () => {
    setPath("/login");

    render(
      <Providers>
        <Probe />
      </Providers>,
    );

    await waitFor(() => expect(countCallsTo("/auth/me")).toBeGreaterThan(0));
    await settle();

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

    await waitFor(() => expect(countCallsTo("/auth/me")).toBeGreaterThan(0));
    await settle();

    expect(replace).not.toHaveBeenCalled();
    expect(countCallsTo("/auth/me")).toBe(1);
  });
});
