import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, apiFetchBlob } from "./client";
import { ApiError, HTTP_ERROR_CODE, INVALID_RESPONSE_CODE, NETWORK_ERROR_CODE } from "./errors";
import { onSessionExpired } from "./session-events";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}

function errorResponse(code: string, status: number, init: ResponseInit = {}): Response {
  return jsonResponse(
    { error: { code, message: code, details: [], request_id: null } },
    { status, ...init },
  );
}

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => null,
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

function clearCsrfCookie(): void {
  document.cookie = "recall_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
}

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    clearCsrfCookie();
  });

  it("calls the proxied API path and parses JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "ok" }));

    await expect(apiFetch("/health/live")).resolves.toEqual({ status: "ok" });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/health/live");
    expect(init?.credentials).toBe("same-origin");
    expect(new Headers(init?.headers).get("Accept")).toBe("application/json");
  });

  it("serialises a JSON body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "w1" }, { status: 201 }));

    await apiFetch("/workspaces", { method: "POST", json: { name: "Databases" } });

    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.body).toBe(JSON.stringify({ name: "Databases" }));
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  it("returns undefined for 204 No Content", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await expect(apiFetch("/documents/d1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("turns the unified error body into an ApiError", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "workspace_not_found",
            message: "Workspace not found.",
            details: [{ field: null, message: "gone" }],
            request_id: "req-12345678",
          },
        },
        { status: 404 },
      ),
    );

    const error = await captureError(apiFetch("/workspaces/w1"));

    expect(error.status).toBe(404);
    expect(error.code).toBe("workspace_not_found");
    expect(error.message).toBe("Workspace not found.");
    expect(error.details).toEqual([{ field: null, message: "gone" }]);
    expect(error.requestId).toBe("req-12345678");
  });

  it("handles an HTML error page from a proxy", async () => {
    fetchMock.mockResolvedValue(
      new Response("<html>Bad Gateway</html>", {
        status: 502,
        statusText: "Bad Gateway",
        headers: { "X-Request-ID": "edge-12345678" },
      }),
    );

    const error = await captureError(apiFetch("/health/ready"));

    expect(error.status).toBe(502);
    expect(error.code).toBe(HTTP_ERROR_CODE);
    expect(error.requestId).toBe("edge-12345678");
    expect(error.body).toBe("<html>Bad Gateway</html>");
  });

  it("keeps a JSON body that is not an error envelope", async () => {
    const readiness = { status: "unavailable", checks: { redis: { status: "error" } } };
    fetchMock.mockResolvedValue(jsonResponse(readiness, { status: 503 }));

    const error = await captureError(apiFetch("/health/ready"));

    expect(error.code).toBe(HTTP_ERROR_CODE);
    expect(error.body).toEqual(readiness);
  });

  it("turns an invalid JSON success response into an ApiError", async () => {
    fetchMock.mockResolvedValue(
      new Response("<html>not json</html>", {
        status: 200,
        headers: { "Content-Type": "text/html", "X-Request-ID": "edge-87654321" },
      }),
    );

    const error = await captureError(apiFetch("/health/live"));

    expect(error.status).toBe(200);
    expect(error.code).toBe(INVALID_RESPONSE_CODE);
    expect(error.requestId).toBe("edge-87654321");
    expect(error.body).toBe("<html>not json</html>");
  });

  it("reports network failures with status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await captureError(apiFetch("/health/live"));

    expect(error.status).toBe(0);
    expect(error.code).toBe(NETWORK_ERROR_CODE);
  });

  it("captures Retry-After as retryAfterSeconds", async () => {
    fetchMock.mockResolvedValue(
      errorResponse("rate_limited", 429, { headers: { "Retry-After": "30" } }),
    );

    const error = await captureError(apiFetch("/auth/login", { method: "POST" }));

    expect(error.retryAfterSeconds).toBe(30);
  });

  it("sends the CSRF token from the cookie on a mutating request", async () => {
    document.cookie = "recall_csrf=token-123";
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiFetch("/workspaces", { method: "POST", json: { name: "x" } });

    const init = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("token-123");
  });

  it("does not send a CSRF token on a GET request", async () => {
    document.cookie = "recall_csrf=token-123";
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await apiFetch("/health/live");

    const init = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("X-CSRF-Token")).toBeNull();
  });

  it("refreshes the session exactly once for two concurrent 401s and retries both", async () => {
    const callCounts = new Map<string, number>();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse({ status: "ok" });
      }
      const count = (callCounts.get(url) ?? 0) + 1;
      callCounts.set(url, count);
      if (count === 1) {
        return errorResponse("token_expired", 401);
      }
      return jsonResponse({ ok: true, url });
    });

    const [a, b] = await Promise.all([apiFetch("/workspaces/a"), apiFetch("/workspaces/b")]);

    expect(a).toEqual({ ok: true, url: "/api/v1/workspaces/a" });
    expect(b).toEqual({ ok: true, url: "/api/v1/workspaces/b" });
    const refreshCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it("refreshes the session on an invalid_token 401 and retries", async () => {
    const callCounts = new Map<string, number>();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse({ status: "ok" });
      }
      const count = (callCounts.get(url) ?? 0) + 1;
      callCounts.set(url, count);
      if (count === 1) {
        return errorResponse("invalid_token", 401);
      }
      return jsonResponse({ ok: true });
    });

    await expect(apiFetch("/workspaces/a")).resolves.toEqual({ ok: true });

    const refreshCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it("emits sessionExpired once and rethrows for invalid_token when the refresh fails", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return errorResponse("invalid_refresh_token", 401);
      }
      return errorResponse("invalid_token", 401);
    });
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);

    const error = await captureError(apiFetch("/workspaces/a"));

    expect(error.code).toBe("invalid_token");
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("never refreshes for auth endpoints themselves", async () => {
    fetchMock.mockResolvedValue(errorResponse("token_expired", 401));

    const error = await captureError(
      apiFetch("/auth/login", { method: "POST", json: { email: "a@example.com", password: "x" } }),
    );

    expect(error.code).toBe("token_expired");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("emits sessionExpired once and throws the original error when the refresh fails", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return errorResponse("invalid_refresh_token", 401);
      }
      return errorResponse("not_authenticated", 401);
    });
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);

    const error = await captureError(apiFetch("/workspaces/a"));

    expect(error.code).toBe("not_authenticated");
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});

describe("apiFetchBlob", () => {
  const FILE_PATH = "/documents/d1/file";

  // Depending on the Node version, fetch builds the Blob from Node's class, which has text(),
  // or from jsdom's global one, which only FileReader can read.
  function readText(blob: Blob): Promise<string> {
    if ("text" in blob) {
      return blob.text();
    }
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(blob);
    });
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("reads the body of the proxied API path as a Blob", async () => {
    fetchMock.mockResolvedValue(
      new Response("# Lecture 1", { headers: { "Content-Type": "text/markdown" } }),
    );

    const blob = await apiFetchBlob(FILE_PATH);

    expect(blob.type).toBe("text/markdown");
    await expect(readText(blob)).resolves.toBe("# Lecture 1");
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/documents/d1/file");
    expect(init?.credentials).toBe("same-origin");
    expect(new Headers(init?.headers).get("Accept")).toBe("*/*");
  });

  it("turns the unified error body into an ApiError", async () => {
    fetchMock.mockResolvedValue(errorResponse("document_file_missing", 404));

    const error = await captureError(apiFetchBlob(FILE_PATH));

    expect(error.status).toBe(404);
    expect(error.code).toBe("document_file_missing");
  });

  it("reports network failures with status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await captureError(apiFetchBlob(FILE_PATH));

    expect(error.status).toBe(0);
    expect(error.code).toBe(NETWORK_ERROR_CODE);
  });

  it("refreshes the session on a 401 and downloads again", async () => {
    let downloads = 0;
    fetchMock.mockImplementation(async (input) => {
      if (String(input).endsWith("/auth/refresh")) {
        return jsonResponse({ status: "ok" });
      }
      downloads += 1;
      if (downloads === 1) {
        return errorResponse("token_expired", 401);
      }
      return new Response("%PDF-1.7", { headers: { "Content-Type": "application/pdf" } });
    });

    const blob = await apiFetchBlob(FILE_PATH);

    await expect(readText(blob)).resolves.toBe("%PDF-1.7");
    expect(downloads).toBe(2);
    const refreshCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it("emits sessionExpired once and throws the original error when the refresh fails", async () => {
    fetchMock.mockImplementation(async (input) => {
      if (String(input).endsWith("/auth/refresh")) {
        return errorResponse("invalid_refresh_token", 401);
      }
      return errorResponse("token_expired", 401);
    });
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);

    const error = await captureError(apiFetchBlob(FILE_PATH));

    expect(error.code).toBe("token_expired");
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});
