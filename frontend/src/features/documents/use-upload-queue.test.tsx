import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentOut } from "@/lib/api/types";

import type { FileRules } from "./file-rules";
import { WORKSPACE_ID, documentFixture } from "./test-fixtures";
import { useUploadQueue, type UploadItem } from "./use-upload-queue";

const MIB = 1024 * 1024;
const RULES: FileRules = {
  allowed_extensions: [".pdf", ".md", ".txt"],
  max_upload_bytes: 20 * MIB,
};
const UPLOAD_URL = `/api/v1/workspaces/${WORKSPACE_ID}/documents`;
const REFRESH_URL = "/api/v1/auth/refresh";

const fetchMock = vi.fn<typeof fetch>();

function textFile(name: string, size?: number): File {
  const file = new File(["# Notes"], name);
  if (size !== undefined) {
    Object.defineProperty(file, "size", { value: size });
  }
  return file;
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function accepted(name: string): Response {
  const document: DocumentOut = documentFixture(1, { original_filename: name });
  return jsonResponse(document, 202);
}

function refused(code: string, status: number, headers: Record<string, string> = {}): Response {
  return jsonResponse(
    { error: { code, message: "The backend's own English.", details: [], request_id: null } },
    status,
    headers,
  );
}

function uploadCalls() {
  return fetchMock.mock.calls.filter(([url]) => String(url) === UPLOAD_URL);
}

/** The names of the files sent so far, in order. */
function sentNames(): string[] {
  return uploadCalls().map(([, init]) => {
    const file = init?.body instanceof FormData ? init.body.get("file") : null;
    return file instanceof File ? file.name : "";
  });
}

/** Answers every upload with the next response, each one given when the test says so. */
function answerUploadsOneByOne() {
  const pending: Array<(response: Response) => void> = [];
  fetchMock.mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        pending.push(resolve);
      }),
  );
  return {
    /** Answers the upload in flight, once it has been sent. */
    async answer(response: Response) {
      await waitFor(() => expect(pending).not.toHaveLength(0));
      const next = pending.shift();
      await act(async () => {
        next?.(response);
      });
    },
  };
}

function states(items: UploadItem[]): string[] {
  return items.map((item) => `${item.name}:${item.state.kind}`);
}

function renderQueue() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { ...renderHook(() => useUploadQueue(WORKSPACE_ID), { wrapper: Wrapper }), queryClient };
}

describe("useUploadQueue", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("sends an accepted file to the workspace as multipart form data", async () => {
    fetchMock.mockResolvedValue(accepted("notes.md"));
    const { result } = renderQueue();

    act(() => result.current.add([textFile("notes.md")], RULES));

    await waitFor(() => expect(states(result.current.items)).toEqual(["notes.md:uploaded"]));
    const [url, init] = uploadCalls()[0] ?? [];
    expect(url).toBe(UPLOAD_URL);
    expect(init?.method).toBe("POST");
    expect(sentNames()).toEqual(["notes.md"]);
    expect(result.current.items[0]?.size).toBe(7);
    expect(result.current.isUploading).toBe(false);
  });

  it("turns down files that break a rule and never sends them", () => {
    const { result } = renderQueue();

    act(() =>
      result.current.add(
        [textFile("timetable.docx"), textFile("empty.md", 0), textFile("scan.pdf", 20 * MIB + 1)],
        RULES,
      ),
    );

    expect(result.current.items.map((item) => item.state)).toEqual([
      { kind: "rejected", reason: "type", rules: RULES },
      { kind: "rejected", reason: "empty", rules: RULES },
      { kind: "rejected", reason: "tooLarge", rules: RULES },
    ]);
    expect(result.current.isUploading).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends files one at a time, in the order they were added", async () => {
    const uploads = answerUploadsOneByOne();
    const { result } = renderQueue();

    act(() =>
      result.current.add(
        [textFile("a.md"), textFile("photo.png"), textFile("b.pdf"), textFile("c.txt")],
        RULES,
      ),
    );

    expect(sentNames()).toEqual(["a.md"]);
    expect(states(result.current.items)).toEqual([
      "a.md:uploading",
      "photo.png:rejected",
      "b.pdf:waiting",
      "c.txt:waiting",
    ]);
    expect(result.current.isUploading).toBe(true);

    await uploads.answer(accepted("a.md"));
    await waitFor(() => expect(sentNames()).toEqual(["a.md", "b.pdf"]));
    expect(states(result.current.items)).toEqual([
      "a.md:uploaded",
      "photo.png:rejected",
      "b.pdf:uploading",
      "c.txt:waiting",
    ]);

    await uploads.answer(accepted("b.pdf"));
    await uploads.answer(accepted("c.txt"));

    await waitFor(() => expect(result.current.isUploading).toBe(false));
    expect(sentNames()).toEqual(["a.md", "b.pdf", "c.txt"]);
    expect(states(result.current.items)).toEqual([
      "a.md:uploaded",
      "photo.png:rejected",
      "b.pdf:uploaded",
      "c.txt:uploaded",
    ]);
  });

  it("sends files added during a run after the ones already waiting", async () => {
    const uploads = answerUploadsOneByOne();
    const { result } = renderQueue();
    act(() => result.current.add([textFile("a.md"), textFile("b.md")], RULES));

    act(() => result.current.add([textFile("c.md"), textFile("notes.docx")], RULES));

    expect(states(result.current.items)).toEqual([
      "a.md:uploading",
      "b.md:waiting",
      "c.md:waiting",
      "notes.docx:rejected",
    ]);
    await uploads.answer(accepted("a.md"));
    await uploads.answer(accepted("b.md"));
    await uploads.answer(accepted("c.md"));
    await waitFor(() => expect(result.current.isUploading).toBe(false));
    expect(sentNames()).toEqual(["a.md", "b.md", "c.md"]);
  });

  it("starts a new list for files added once a run is over", async () => {
    fetchMock.mockImplementation(async () => accepted("x.md"));
    const { result } = renderQueue();
    act(() => result.current.add([textFile("a.md"), textFile("notes.docx")], RULES));
    await waitFor(() => expect(result.current.isUploading).toBe(false));

    act(() => result.current.add([textFile("b.md")], RULES));

    expect(states(result.current.items)).toEqual(["b.md:uploading"]);
    await waitFor(() => expect(states(result.current.items)).toEqual(["b.md:uploaded"]));
  });

  it("keeps the reason a file was refused and goes on with the next one", async () => {
    fetchMock
      .mockResolvedValueOnce(refused("duplicate_document", 409))
      .mockResolvedValueOnce(accepted("b.md"));
    const { result } = renderQueue();

    act(() => result.current.add([textFile("a.md"), textFile("b.md")], RULES));

    await waitFor(() => expect(result.current.isUploading).toBe(false));
    expect(states(result.current.items)).toEqual(["a.md:failed", "b.md:uploaded"]);
    const refusal = result.current.items[0]?.state;
    expect(refusal?.kind === "failed" && refusal.error).toMatchObject({
      status: 409,
      code: "duplicate_document",
    });
  });

  it.each([
    ["rate_limited", "120", 120],
    ["too_many_active_documents", "60", 60],
  ])("stops at the first %s and keeps the files left unsent", async (code, retryAfter, seconds) => {
    fetchMock
      .mockResolvedValueOnce(accepted("a.md"))
      .mockResolvedValueOnce(refused(code, 429, { "Retry-After": retryAfter }))
      .mockResolvedValue(accepted("never.md"));
    const { result } = renderQueue();

    act(() =>
      result.current.add(
        [textFile("a.md"), textFile("b.md"), textFile("c.md"), textFile("d.txt")],
        RULES,
      ),
    );

    await waitFor(() => expect(result.current.isUploading).toBe(false));
    expect(sentNames()).toEqual(["a.md", "b.md"]);
    expect(states(result.current.items)).toEqual([
      "a.md:uploaded",
      "b.md:failed",
      "c.md:notSent",
      "d.txt:notSent",
    ]);
    expect(result.current.items[2]?.state).toEqual({
      kind: "notSent",
      retryAfterSeconds: seconds,
    });
  });

  it("keeps files unsent when the rate limit names no wait", async () => {
    fetchMock.mockResolvedValueOnce(refused("rate_limited", 429));
    const { result } = renderQueue();

    act(() => result.current.add([textFile("a.md"), textFile("b.md")], RULES));

    await waitFor(() => expect(result.current.isUploading).toBe(false));
    expect(result.current.items[1]?.state).toEqual({ kind: "notSent", retryAfterSeconds: null });
  });

  it("refreshes the workspace queries after each upload, not after a refusal", async () => {
    fetchMock
      .mockResolvedValueOnce(accepted("a.md"))
      .mockResolvedValueOnce(refused("empty_file", 422))
      .mockResolvedValueOnce(accepted("c.md"));
    const { result, queryClient } = renderQueue();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    act(() => result.current.add([textFile("a.md"), textFile("b.md"), textFile("c.md")], RULES));

    await waitFor(() => expect(result.current.isUploading).toBe(false));
    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["workspaces"] });
  });

  it("sends the file once more after the session is refreshed", async () => {
    let uploads = 0;
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === REFRESH_URL) {
        return jsonResponse({ status: "ok" });
      }
      uploads += 1;
      return uploads === 1 ? refused("not_authenticated", 401) : accepted("notes.md");
    });
    const { result } = renderQueue();

    act(() => result.current.add([textFile("notes.md")], RULES));

    await waitFor(() => expect(states(result.current.items)).toEqual(["notes.md:uploaded"]));
    expect(sentNames()).toEqual(["notes.md", "notes.md"]);
    const refreshes = fetchMock.mock.calls.filter(([url]) => String(url) === REFRESH_URL);
    expect(refreshes).toHaveLength(1);
  });

  it("sends a file to the workspace it was added for", async () => {
    fetchMock.mockImplementation(async () => accepted("notes.md"));
    const queryClient = new QueryClient();
    const { result, rerender } = renderHook(({ id }) => useUploadQueue(id), {
      initialProps: { id: WORKSPACE_ID },
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      ),
    });

    act(() => result.current.add([textFile("notes.md")], RULES));
    rerender({ id: "00000000-0000-4000-8000-000000000002" });

    await waitFor(() => expect(result.current.isUploading).toBe(false));
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([UPLOAD_URL]);
  });

  it("forgets the list on clear", async () => {
    fetchMock.mockResolvedValue(accepted("notes.md"));
    const { result } = renderQueue();
    act(() => result.current.add([textFile("notes.md"), textFile("notes.docx")], RULES));
    await waitFor(() => expect(result.current.isUploading).toBe(false));

    act(() => result.current.clear());

    expect(result.current.items).toEqual([]);
  });
});
