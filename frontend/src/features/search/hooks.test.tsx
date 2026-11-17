import { act, renderHook, waitFor } from "@testing-library/react";
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WORKSPACE_ID } from "@/features/documents/test-fixtures";
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

import { useSearch } from "./hooks";
import { searchResultsFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const LIGHT_PATH = `/search?workspace_id=${WORKSPACE_ID}&q=light+reactions&limit=10`;
const DAY_MS = 24 * 60 * 60 * 1000;

/** A client that retries failures and refreshes on focus, as queries do unless told otherwise. */
function newQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: 3, retryDelay: 0 } } });
}

function renderSearch(query: string | null, queryClient = newQueryClient()) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  const rendered = renderHook((current: string | null) => useSearch(WORKSPACE_ID, current), {
    wrapper: Wrapper,
    initialProps: query,
  });
  return { ...rendered, queryClient };
}

function showTabAgain(): void {
  act(() => {
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
  });
}

function comeBackOnline(): void {
  act(() => {
    onlineManager.setOnline(false);
    onlineManager.setOnline(true);
  });
}

function signalOf(call: number): AbortSignal | null | undefined {
  return apiFetchMock.mock.calls[call]?.[1]?.signal;
}

describe("useSearch", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("asks for nothing without a query", async () => {
    apiFetchMock.mockResolvedValue(searchResultsFixture(1));
    const { result } = renderSearch(null);

    await act(() => Promise.resolve());

    expect(result.current.fetchStatus).toBe("idle");
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("asks for the passages of the workspace that match the query", async () => {
    const results = searchResultsFixture(2);
    apiFetchMock.mockResolvedValue(results);
    const { result } = renderSearch("light reactions");

    await waitFor(() => expect(result.current.data).toEqual(results));
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(apiFetchMock).toHaveBeenCalledWith(LIGHT_PATH, { signal: expect.any(AbortSignal) });
  });

  it("never asks again by itself: not when the tab is shown again, nor when the page comes back soon", async () => {
    apiFetchMock.mockResolvedValue(searchResultsFixture(2));
    const { result, unmount, queryClient } = renderSearch("light reactions");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    showTabAgain();
    unmount();
    const again = renderSearch("light reactions", queryClient);
    await waitFor(() => expect(again.result.current.isSuccess).toBe(true));
    showTabAgain();

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps an answer however old it is", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      apiFetchMock.mockResolvedValue(searchResultsFixture(2));
      const { result, unmount, queryClient } = renderSearch("light reactions");
      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      vi.setSystemTime(Date.now() + DAY_MS);
      unmount();
      const again = renderSearch("light reactions", queryClient);
      await waitFor(() => expect(again.result.current.isSuccess).toBe(true));
      comeBackOnline();
      await act(() => Promise.resolve());

      expect(apiFetchMock).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not try a failed search again when the tab is shown again or the browser is back online", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 503, code: "http_error", message: "Service Unavailable" }),
    );
    const { result } = renderSearch("light reactions");
    await waitFor(() => expect(result.current.isError).toBe(true));

    // A failed search has no answer to keep, so only the options stop these from asking.
    showTabAgain();
    comeBackOnline();
    await act(() => Promise.resolve());

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("asks a failed search again when the page comes back, as it has no answer to show", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 503, code: "http_error", message: "Service Unavailable" }),
    );
    const { result, unmount, queryClient } = renderSearch("light reactions");
    await waitFor(() => expect(result.current.isError).toBe(true));

    unmount();
    const again = renderSearch("light reactions", queryClient);
    await waitFor(() => expect(again.result.current.isFetching).toBe(false));

    expect(again.result.current.isError).toBe(true);
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
  });

  it("asks again when told to, for the same query", async () => {
    apiFetchMock.mockResolvedValue(searchResultsFixture(2));
    const { result } = renderSearch("light reactions");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await act(() => result.current.refetch());

    expect(apiFetchMock).toHaveBeenCalledTimes(2);
    expect(apiFetchMock).toHaveBeenLastCalledWith(LIGHT_PATH, {
      signal: expect.any(AbortSignal),
    });
  });

  it("stops the request of a query left for another", async () => {
    apiFetchMock.mockReturnValueOnce(new Promise(() => {}));
    apiFetchMock.mockResolvedValue(searchResultsFixture(1));
    const { result, rerender } = renderSearch("light reactions");
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));

    rerender("glucose");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiFetchMock).toHaveBeenLastCalledWith(
      `/search?workspace_id=${WORKSPACE_ID}&q=glucose&limit=10`,
      { signal: expect.any(AbortSignal) },
    );
    expect(signalOf(0)?.aborted).toBe(true);
    expect(signalOf(1)?.aborted).toBe(false);
  });

  it("keeps each search under its workspace and query", async () => {
    const results = searchResultsFixture(2);
    apiFetchMock.mockResolvedValue(results);
    const { result, queryClient } = renderSearch("light reactions");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(queryClient.getQueryData(["search", WORKSPACE_ID, "light reactions"])).toEqual(results);
  });
});
