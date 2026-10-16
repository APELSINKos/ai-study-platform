import { act, renderHook } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  defaultScheduler,
  notifyManager,
} from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";

import { useWorkspaceDocuments } from "./hooks";
import {
  WORKSPACE_ID,
  documentFixture,
  documentPageFixture,
  readyDocumentFixture,
} from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const FIRST_PAGE_PATH = `/workspaces/${WORKSPACE_ID}/documents?page=1&page_size=50`;
const SECOND_PAGE_PATH = `/workspaces/${WORKSPACE_ID}/documents?page=2&page_size=50`;

const processing = documentFixture(1, { status: "processing" });

function page(...items: DocumentOut[]) {
  return documentPageFixture(items);
}

function renderDocuments() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return {
    ...renderHook(() => useWorkspaceDocuments(WORKSPACE_ID), { wrapper: Wrapper }),
    queryClient,
  };
}

/** Lets the time pass, with every request and update it brings. */
async function pass(ms: number): Promise<void> {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}

function requests(): number {
  return apiFetchMock.mock.calls.length;
}

describe("useWorkspaceDocuments", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    // Updates normally reach React in a zero-delay timer, which the fake clock runs a
    // millisecond late when a request ends inside a tick; a microtask keeps every step exact.
    notifyManager.setScheduler(queueMicrotask);
  });

  afterEach(() => {
    notifyManager.setScheduler(defaultScheduler);
    vi.useRealTimers();
  });

  it("asks for the first fifty documents of the workspace", async () => {
    apiFetchMock.mockResolvedValue(page(readyDocumentFixture(1)));
    const { result } = renderDocuments();

    await pass(0);

    expect(apiFetchMock).toHaveBeenCalledWith(FIRST_PAGE_PATH);
    expect(result.current.data?.documents.map((document) => document.original_filename)).toEqual([
      "lecture-1.pdf",
    ]);
    expect(result.current.data?.total).toBe(1);
  });

  it("counts the documents of pages not loaded yet", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => readyDocumentFixture(index + 1));
    apiFetchMock.mockResolvedValue(documentPageFixture(firstFifty, { total: 73 }));
    const { result } = renderDocuments();

    await pass(0);

    expect(result.current.data?.documents).toHaveLength(50);
    expect(result.current.data?.total).toBe(73);
  });

  it("shows the loaded pages as one list and a document pushed onto the next page once", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => readyDocumentFixture(index + 1));
    // A file uploaded meanwhile moved every document down one place.
    apiFetchMock
      .mockResolvedValueOnce(documentPageFixture(firstFifty, { total: 52 }))
      .mockResolvedValueOnce(
        documentPageFixture([readyDocumentFixture(50), readyDocumentFixture(51)], {
          page: 2,
          total: 52,
        }),
      );
    const { result } = renderDocuments();
    await pass(0);
    expect(result.current.hasNextPage).toBe(true);

    await act(() => result.current.fetchNextPage());
    await pass(0);

    expect(apiFetchMock).toHaveBeenLastCalledWith(SECOND_PAGE_PATH);
    const ids = result.current.data?.documents.map((document) => document.id) ?? [];
    expect(ids).toHaveLength(51);
    expect(new Set(ids).size).toBe(51);
    expect(result.current.data?.total).toBe(52);
    expect(result.current.hasNextPage).toBe(false);
  });

  it("asks again every two seconds while a document is on its way, and stops once it is done", async () => {
    apiFetchMock
      .mockResolvedValueOnce(page(processing))
      .mockResolvedValueOnce(page({ ...processing, status: "indexing" }))
      .mockResolvedValue(page(readyDocumentFixture(1)));
    const { result } = renderDocuments();
    await pass(0);
    expect(result.current.data?.documents[0]?.status).toBe("processing");

    await pass(1999);
    expect(requests()).toBe(1);
    await pass(1);
    expect(requests()).toBe(2);
    expect(result.current.data?.documents[0]?.status).toBe("indexing");

    await pass(2000);
    expect(requests()).toBe(3);
    expect(result.current.data?.documents[0]?.status).toBe("ready");

    await pass(60_000);
    expect(requests()).toBe(3);
  });

  it("never asks again when every document is ready or failed", async () => {
    apiFetchMock.mockResolvedValue(
      page(
        readyDocumentFixture(1),
        documentFixture(2, { status: "failed", error_code: "no_text", can_retry: true }),
      ),
    );
    renderDocuments();
    await pass(0);

    await pass(60_000);

    expect(requests()).toBe(1);
  });

  it("asks every fifteen seconds when each document on its way has stalled", async () => {
    apiFetchMock.mockResolvedValue(
      page(documentFixture(1, { status: "indexing", can_retry: true }), readyDocumentFixture(2)),
    );
    renderDocuments();
    await pass(0);

    await pass(14_999);
    expect(requests()).toBe(1);
    await pass(1);
    expect(requests()).toBe(2);
  });

  it("stops asking after a 4xx answer and starts again once a later request succeeds", async () => {
    apiFetchMock
      .mockResolvedValueOnce(page(processing))
      .mockRejectedValueOnce(
        new ApiError({ status: 404, code: "workspace_not_found", message: "x" }),
      )
      .mockResolvedValue(page(processing));
    const { result, queryClient } = renderDocuments();
    await pass(0);
    await pass(2000);
    expect(requests()).toBe(2);
    expect(result.current.error).toBeInstanceOf(ApiError);

    await pass(60_000);
    expect(requests()).toBe(2);

    await act(() =>
      queryClient.refetchQueries({ queryKey: queryKeys.workspaceDocuments(WORKSPACE_ID) }),
    );
    await pass(0);
    expect(requests()).toBe(3);
    expect(result.current.error).toBeNull();

    await pass(2000);
    expect(requests()).toBe(4);
  });

  it.each([
    ["a server failure", new ApiError({ status: 503, code: "http_error", message: "x" })],
    ["a lost connection", new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "x" })],
  ])("keeps asking after %s", async (_, failure) => {
    apiFetchMock
      .mockResolvedValueOnce(page(processing))
      .mockRejectedValueOnce(failure)
      .mockResolvedValue(page(processing));
    const { result } = renderDocuments();
    await pass(0);
    await pass(2000);
    expect(result.current.error).toBe(failure);
    expect(result.current.data?.documents[0]?.status).toBe("processing");

    await pass(2000);

    expect(requests()).toBe(3);
  });

  it("starts asking again when a document in the cache goes back on its way", async () => {
    const failed = documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true });
    apiFetchMock.mockResolvedValueOnce(page(failed)).mockResolvedValue(page(processing));
    const { queryClient } = renderDocuments();
    await pass(0);
    await pass(10_000);
    expect(requests()).toBe(1);

    act(() => {
      queryClient.setQueryData(queryKeys.workspaceDocuments(WORKSPACE_ID), {
        pages: [page({ ...failed, status: "uploaded", error_code: null, can_retry: false })],
        pageParams: [1],
      });
    });
    await pass(2000);

    expect(requests()).toBe(2);
  });
});
