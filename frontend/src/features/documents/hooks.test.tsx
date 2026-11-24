import { act, renderHook, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  defaultScheduler,
  notifyManager,
} from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSearch } from "@/features/search/hooks";
import { searchResultsFixture } from "@/features/search/test-fixtures";
import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";

import {
  useDeleteDocument,
  useDocument,
  useDocumentChunks,
  useRetryDocument,
  useWorkspaceDocuments,
} from "./hooks";
import {
  WORKSPACE_ID,
  chunkFixture,
  chunkPageFixture,
  documentFixture,
  documentPageFixture,
  readyDocumentFixture,
} from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const FIRST_PAGE_PATH = `/workspaces/${WORKSPACE_ID}/documents?page=1&page_size=50`;
const SECOND_PAGE_PATH = `/workspaces/${WORKSPACE_ID}/documents?page=2&page_size=50`;

const processing = documentFixture(1, { status: "processing" });
const DOCUMENT_PATH = `/documents/${processing.id}`;
const FIRST_CHUNKS_PATH = `${DOCUMENT_PATH}/chunks?page=1&page_size=50`;
const SECOND_CHUNKS_PATH = `${DOCUMENT_PATH}/chunks?page=2&page_size=50`;

function page(...items: DocumentOut[]) {
  return documentPageFixture(items);
}

function newQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWithClient<Result>(hook: () => Result) {
  const queryClient = newQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { ...renderHook(hook, { wrapper: Wrapper }), queryClient };
}

function renderDocuments() {
  return renderWithClient(() => useWorkspaceDocuments(WORKSPACE_ID));
}

/** The fragments of a document whose state the test changes with `rerender`. */
function renderChunks(document: DocumentOut) {
  const queryClient = newQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return renderHook((current: DocumentOut) => useDocumentChunks(current), {
    wrapper: Wrapper,
    initialProps: document,
  });
}

/** Lets the time pass, with every request and update it brings. */
async function pass(ms: number): Promise<void> {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}

function requests(): number {
  return apiFetchMock.mock.calls.length;
}

/** Runs the tests of a block on a fake clock, so that polling can be stepped through. */
function withFakeClock(): void {
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
}

describe("useWorkspaceDocuments", () => {
  withFakeClock();

  it("asks for the first fifty documents of the workspace", async () => {
    apiFetchMock.mockResolvedValue(page(readyDocumentFixture(1)));
    const { result } = renderDocuments();

    await pass(0);

    expect(apiFetchMock).toHaveBeenCalledWith(FIRST_PAGE_PATH, {
      signal: expect.any(AbortSignal),
    });
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

    expect(apiFetchMock).toHaveBeenLastCalledWith(SECOND_PAGE_PATH, {
      signal: expect.any(AbortSignal),
    });
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

  it("asks every two seconds again once a failed document is retried", async () => {
    const failed = documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true });
    const queued: DocumentOut = {
      ...failed,
      status: "uploaded",
      error_code: null,
      can_retry: false,
    };
    let retried = false;
    apiFetchMock.mockImplementation(async (_path, init) => {
      if (init?.method === "POST") {
        retried = true;
        return queued;
      }
      return page(retried ? queued : failed);
    });
    const { result } = renderWithClient(() => ({
      list: useWorkspaceDocuments(WORKSPACE_ID),
      retry: useRetryDocument(failed),
    }));
    const listRequests = () =>
      apiFetchMock.mock.calls.filter(([, init]) => init?.method !== "POST").length;
    await pass(0);
    await pass(10_000);
    expect(listRequests()).toBe(1);

    await act(() => result.current.retry.mutateAsync());
    await pass(0);
    expect(result.current.list.data?.documents[0]?.status).toBe("uploaded");
    const afterRetry = listRequests();

    await pass(2000);

    expect(listRequests()).toBe(afterRetry + 1);
  });

  it("refreshes workspace stats when a document finishes processing, not on intermediate stages or pagination", async () => {
    apiFetchMock
      .mockResolvedValueOnce(page(processing))
      .mockResolvedValueOnce(page({ ...processing, status: "indexing" }))
      .mockResolvedValue(page(readyDocumentFixture(1)));
    const { queryClient } = renderDocuments();
    queryClient.setQueryData(queryKeys.workspace(WORKSPACE_ID), { id: WORKSPACE_ID });
    queryClient.setQueryData(queryKeys.workspaceList, { pages: [], pageParams: [1] });
    queryClient.setQueryData(queryKeys.recentWorkspaces, { items: [] });

    await pass(0);
    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(false);

    // processing -> indexing is still in progress: workspace stats do not change yet.
    await pass(2000);
    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(false);

    // indexing -> ready settles the document: refresh workspace stats without re-fetching documents.
    await pass(2000);
    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.workspaceList)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.recentWorkspaces)?.isInvalidated).toBe(true);
    expect(
      queryClient.getQueryState(queryKeys.workspaceDocuments(WORKSPACE_ID))?.isInvalidated,
    ).toBe(false);
  });

  it("does not invalidate workspace stats when loading another page of ready documents", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => readyDocumentFixture(index + 1));
    apiFetchMock
      .mockResolvedValueOnce(documentPageFixture(firstFifty, { total: 52 }))
      .mockResolvedValueOnce(
        documentPageFixture([readyDocumentFixture(51), readyDocumentFixture(52)], {
          page: 2,
          total: 52,
        }),
      );
    const { result, queryClient } = renderDocuments();
    queryClient.setQueryData(queryKeys.workspace(WORKSPACE_ID), { id: WORKSPACE_ID });
    await pass(0);

    await act(() => result.current.fetchNextPage());
    await pass(0);

    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(false);
  });

  it("does not falsely invalidate workspace stats when a deletion shifts a ready page-2 doc onto page 1", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => readyDocumentFixture(index + 1));
    const ready51 = readyDocumentFixture(51);
    const processing52 = documentFixture(52, { status: "processing" });
    let shifted = false;
    apiFetchMock.mockImplementation(async (path) => {
      if (path === FIRST_PAGE_PATH) {
        return shifted
          ? documentPageFixture([...firstFifty.slice(1), ready51], { page: 1, total: 51 })
          : documentPageFixture(firstFifty, { page: 1, total: 52 });
      }
      return shifted
        ? documentPageFixture([processing52], { page: 2, total: 51 })
        : documentPageFixture([ready51, processing52], { page: 2, total: 52 });
    });
    const { result, queryClient } = renderDocuments();
    queryClient.setQueryData(queryKeys.workspace(WORKSPACE_ID), { id: WORKSPACE_ID });
    await pass(0);
    await act(() => result.current.fetchNextPage());
    await pass(0);
    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(false);

    // Deleting doc 1 shifts ready doc 51 onto page 1; doc 51 was already ready on page 2.
    shifted = true;
    await pass(2000);

    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(false);
  });

  it("refreshes workspace stats when an active document settles on page 2", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => readyDocumentFixture(index + 1));
    const processing51 = documentFixture(51, { status: "processing" });
    const ready51 = readyDocumentFixture(51);
    let settled = false;
    apiFetchMock.mockImplementation(async (path) => {
      if (path === FIRST_PAGE_PATH) {
        return documentPageFixture(firstFifty, { page: 1, total: 51 });
      }
      return documentPageFixture([settled ? ready51 : processing51], { page: 2, total: 51 });
    });
    const { result, queryClient } = renderDocuments();
    queryClient.setQueryData(queryKeys.workspace(WORKSPACE_ID), { id: WORKSPACE_ID });
    queryClient.setQueryData(queryKeys.workspaceList, { pages: [], pageParams: [1] });
    queryClient.setQueryData(queryKeys.recentWorkspaces, { items: [] });
    await pass(0);
    await act(() => result.current.fetchNextPage());
    await pass(0);
    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(false);

    settled = true;
    await pass(2000);

    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.workspaceList)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.recentWorkspaces)?.isInvalidated).toBe(true);
  });

  it("skips workspace stats invalidation if a polling request was aborted before resolving", async () => {
    const pendingRefetch = Promise.withResolvers<ReturnType<typeof page>>();
    let calls = 0;
    apiFetchMock.mockImplementation(() => {
      calls += 1;
      return calls === 1 ? Promise.resolve(page(processing)) : pendingRefetch.promise;
    });
    const { queryClient } = renderDocuments();
    queryClient.setQueryData(queryKeys.workspace(WORKSPACE_ID), { id: WORKSPACE_ID });
    await pass(0);

    await pass(2000);
    expect(calls).toBe(2);
    await act(() =>
      queryClient.cancelQueries({ queryKey: queryKeys.workspaceDocuments(WORKSPACE_ID) }),
    );
    await act(async () => {
      pendingRefetch.resolve(page(readyDocumentFixture(1)));
      await pendingRefetch.promise;
    });

    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(false);
  });
});

describe("useDocument", () => {
  withFakeClock();

  function renderDocument(id = processing.id) {
    return renderWithClient(() => useDocument(id));
  }

  it("asks for the document the id names", async () => {
    apiFetchMock.mockResolvedValue(readyDocumentFixture(1));
    const { result } = renderDocument();

    await pass(0);

    expect(apiFetchMock).toHaveBeenCalledWith(DOCUMENT_PATH, {
      signal: expect.any(AbortSignal),
    });
    expect(result.current.data?.title).toBe("Lecture 1");
  });

  it("asks again every two seconds while the document is on its way, and stops once it is ready", async () => {
    apiFetchMock
      .mockResolvedValueOnce(processing)
      .mockResolvedValueOnce({ ...processing, status: "indexing" })
      .mockResolvedValue(readyDocumentFixture(1));
    const { result } = renderDocument();
    await pass(0);
    expect(result.current.data?.status).toBe("processing");

    await pass(1999);
    expect(requests()).toBe(1);
    await pass(1);
    expect(requests()).toBe(2);
    expect(result.current.data?.status).toBe("indexing");

    await pass(2000);
    expect(requests()).toBe(3);
    expect(result.current.data?.status).toBe("ready");

    await pass(60_000);
    expect(requests()).toBe(3);
  });

  it("never asks again for a document that failed", async () => {
    apiFetchMock.mockResolvedValue(
      documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true }),
    );
    renderDocument();
    await pass(0);

    await pass(60_000);

    expect(requests()).toBe(1);
  });

  it("asks every fifteen seconds while the document has stalled", async () => {
    apiFetchMock.mockResolvedValue(documentFixture(1, { status: "indexing", can_retry: true }));
    renderDocument();
    await pass(0);

    await pass(14_999);
    expect(requests()).toBe(1);
    await pass(1);
    expect(requests()).toBe(2);
  });

  it("asks for nothing, not even while the document is on its way, when turned off", async () => {
    apiFetchMock.mockResolvedValue(processing);
    let turnedOff = false;
    const { result, rerender } = renderWithClient(() =>
      useDocument(processing.id, { enabled: !turnedOff }),
    );
    await pass(0);
    expect(result.current.data?.status).toBe("processing");

    turnedOff = true;
    rerender();
    await pass(60_000);

    expect(requests()).toBe(1);
  });

  it("stops asking after a 4xx answer", async () => {
    apiFetchMock
      .mockResolvedValueOnce(processing)
      .mockRejectedValue(new ApiError({ status: 404, code: "document_not_found", message: "x" }));
    const { result } = renderDocument();
    await pass(0);
    await pass(2000);
    expect(result.current.error).toBeInstanceOf(ApiError);

    await pass(60_000);

    expect(requests()).toBe(2);
  });

  it("keeps asking after a server failure", async () => {
    const failure = new ApiError({ status: 503, code: "http_error", message: "x" });
    apiFetchMock
      .mockResolvedValueOnce(processing)
      .mockRejectedValueOnce(failure)
      .mockResolvedValue(processing);
    const { result } = renderDocument();
    await pass(0);
    await pass(2000);
    expect(result.current.error).toBe(failure);
    expect(result.current.data?.status).toBe("processing");

    await pass(2000);

    expect(requests()).toBe(3);
  });

  it("keeps the document where the API's spelling of its id finds it", async () => {
    const lettered = readyDocumentFixture(1, { id: "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d" });
    apiFetchMock.mockResolvedValue(lettered);
    const { queryClient } = renderDocument(lettered.id.toUpperCase());

    await pass(0);

    expect(apiFetchMock).toHaveBeenCalledWith(`/documents/${lettered.id.toUpperCase()}`, {
      signal: expect.any(AbortSignal),
    });
    expect(queryClient.getQueryData(queryKeys.document(lettered.id))).toEqual(lettered);
  });

  it("shows a retried document's new state at once", async () => {
    const failed = documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true });
    const queued: DocumentOut = {
      ...failed,
      status: "uploaded",
      error_code: null,
      can_retry: false,
    };
    apiFetchMock.mockImplementation(async (_path, init) =>
      init?.method === "POST" ? queued : failed,
    );
    const { result } = renderWithClient(() => ({
      document: useDocument(failed.id),
      retry: useRetryDocument(failed),
    }));
    await pass(0);
    // The refresh after the retry never lands, so only the retry's answer can move the page on.
    apiFetchMock.mockImplementation((_path, init) =>
      init?.method === "POST" ? Promise.resolve(queued) : new Promise(() => {}),
    );

    await act(() => result.current.retry.mutateAsync());
    await pass(0);

    expect(result.current.document.data?.status).toBe("uploaded");
  });

  it.each([
    ["ready", readyDocumentFixture(1)],
    ["failed", documentFixture(1, { status: "failed", error_code: "no_text", can_retry: true })],
  ])(
    "refreshes workspace stats when an active document settles as %s, not on intermediate stages",
    async (_label, settledDoc) => {
      apiFetchMock
        .mockResolvedValueOnce(processing)
        .mockResolvedValueOnce({ ...processing, status: "indexing" })
        .mockResolvedValue(settledDoc);
      const { queryClient } = renderDocument();
      queryClient.setQueryData(queryKeys.workspace(WORKSPACE_ID), { id: WORKSPACE_ID });
      queryClient.setQueryData(queryKeys.workspaceList, { pages: [], pageParams: [1] });
      queryClient.setQueryData(queryKeys.recentWorkspaces, { items: [] });

      await pass(0);
      expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(
        false,
      );

      await pass(2000);
      expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(
        false,
      );

      await pass(2000);
      expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(
        true,
      );
      expect(queryClient.getQueryState(queryKeys.workspaceList)?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(queryKeys.recentWorkspaces)?.isInvalidated).toBe(true);
      expect(
        queryClient.getQueryState(queryKeys.workspaceDocuments(WORKSPACE_ID))?.isInvalidated,
      ).toBeUndefined();
    },
  );

  it("skips workspace stats invalidation if a single-document poll was aborted before resolving", async () => {
    const pendingRefetch = Promise.withResolvers<DocumentOut>();
    let calls = 0;
    apiFetchMock.mockImplementation(() => {
      calls += 1;
      return calls === 1 ? Promise.resolve(processing) : pendingRefetch.promise;
    });
    const { queryClient } = renderDocument();
    queryClient.setQueryData(queryKeys.workspace(WORKSPACE_ID), { id: WORKSPACE_ID });
    await pass(0);

    await pass(2000);
    expect(calls).toBe(2);
    await act(() => queryClient.cancelQueries({ queryKey: queryKeys.document(processing.id) }));
    await act(async () => {
      pendingRefetch.resolve(readyDocumentFixture(1));
      await pendingRefetch.promise;
    });

    expect(queryClient.getQueryState(queryKeys.workspace(WORKSPACE_ID))?.isInvalidated).toBe(false);
  });
});

describe("useDocumentChunks", () => {
  withFakeClock();

  it("asks for no fragments while the document is on its way", async () => {
    apiFetchMock.mockResolvedValue(chunkPageFixture([chunkFixture(0)]));
    renderChunks(processing);

    await pass(10_000);

    expect(requests()).toBe(0);
  });

  it("asks for the first fifty fragments once the document is ready, and only once", async () => {
    apiFetchMock.mockResolvedValue(chunkPageFixture([chunkFixture(0), chunkFixture(1)]));
    const { result, rerender } = renderChunks(processing);
    await pass(0);

    rerender(readyDocumentFixture(1));
    await pass(0);

    expect(apiFetchMock).toHaveBeenCalledWith(FIRST_CHUNKS_PATH);
    expect(result.current.data?.chunks.map((chunk) => chunk.content)).toEqual([
      "Passage 0 of the lecture.",
      "Passage 1 of the lecture.",
    ]);

    // A fresh copy of the same ready document, as a later refresh of the page brings.
    rerender(readyDocumentFixture(1));
    await pass(60_000);

    expect(requests()).toBe(1);
  });

  it("loads the fragments a page at a time, in reading order", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => chunkFixture(index));
    apiFetchMock
      .mockResolvedValueOnce(chunkPageFixture(firstFifty, { total: 51 }))
      .mockResolvedValueOnce(chunkPageFixture([chunkFixture(50)], { page: 2, total: 51 }));
    const { result } = renderChunks(readyDocumentFixture(1));
    await pass(0);
    expect(result.current.hasNextPage).toBe(true);

    await act(() => result.current.fetchNextPage());
    await pass(0);

    expect(apiFetchMock).toHaveBeenLastCalledWith(SECOND_CHUNKS_PATH);
    expect(result.current.data?.chunks.map((chunk) => chunk.chunk_index)).toEqual(
      Array.from({ length: 51 }, (_, index) => index),
    );
    expect(result.current.hasNextPage).toBe(false);
  });

  it("counts the fragments of pages not loaded yet", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => chunkFixture(index));
    apiFetchMock.mockResolvedValue(chunkPageFixture(firstFifty, { total: 130 }));
    const { result } = renderChunks(readyDocumentFixture(1));

    await pass(0);

    expect(result.current.data?.chunks).toHaveLength(50);
    expect(result.current.data?.total).toBe(130);
  });

  it("never asks for the loaded pages again when the user comes back to the tab", async () => {
    const firstFifty = Array.from({ length: 50 }, (_, index) => chunkFixture(index));
    apiFetchMock.mockImplementation(async (path) =>
      path === FIRST_CHUNKS_PATH
        ? chunkPageFixture(firstFifty, { total: 51 })
        : chunkPageFixture([chunkFixture(50)], { page: 2, total: 51 }),
    );
    const { result } = renderChunks(readyDocumentFixture(1));
    await pass(0);
    await act(() => result.current.fetchNextPage());
    await pass(0);
    expect(requests()).toBe(2);

    // Long after any usual freshness window, the tab is shown again.
    await pass(60_000);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
    });
    await pass(0);

    expect(requests()).toBe(2);
  });
});

describe("useDeleteDocument", () => {
  const OTHER_WORKSPACE_ID = "00000000-0000-4000-8000-000000000002";

  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("leaves the searches of the document's workspace to be run again, and only those", async () => {
    apiFetchMock.mockResolvedValue(undefined);
    const { result, queryClient } = renderWithClient(() =>
      useDeleteDocument(readyDocumentFixture(1)),
    );
    const searches = [
      queryKeys.search(WORKSPACE_ID, "light"),
      queryKeys.search(WORKSPACE_ID, "glucose"),
      queryKeys.search(OTHER_WORKSPACE_ID, "light"),
    ];
    for (const key of searches) {
      queryClient.setQueryData(key, searchResultsFixture(2));
    }

    await act(() => result.current.mutateAsync());

    // Its passages may be among the results; a search on screen runs again at once.
    const invalidated = searches.map((key) => queryClient.getQueryState(key)?.isInvalidated);
    expect(invalidated).toEqual([true, true, false]);
  });

  it("sends again a search that was still on its way when the document went", async () => {
    let searches = 0;
    apiFetchMock.mockImplementation(async (path) => {
      if (!path.startsWith("/search")) {
        return undefined;
      }
      searches += 1;
      // The first answer may have been worked out before the delete: it never arrives here.
      return searches === 1 ? new Promise(() => {}) : searchResultsFixture(1);
    });
    const { result } = renderWithClient(() => ({
      search: useSearch(WORKSPACE_ID, "light"),
      remove: useDeleteDocument(readyDocumentFixture(1)),
    }));
    await waitFor(() => expect(searches).toBe(1));

    await act(() => result.current.remove.mutateAsync());

    await waitFor(() => expect(result.current.search.isSuccess).toBe(true));
    expect(searches).toBe(2);
  });
});
