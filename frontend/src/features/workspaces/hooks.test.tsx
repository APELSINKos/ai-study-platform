import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { searchResultsFixture } from "@/features/search/test-fixtures";
import { apiFetch } from "@/lib/api/client";
import { queryKeys } from "@/lib/query-keys";

import { useDeleteWorkspace, useUpdateWorkspace } from "./hooks";
import { workspaceFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const DELETED = workspaceFixture(1);
const KEPT = workspaceFixture(2);

function renderHookWithClient<T>(hook: () => T) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { ...renderHook(hook, { wrapper: Wrapper }), queryClient };
}

describe("useDeleteWorkspace", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("forgets the searches of the deleted workspace, and only those", async () => {
    apiFetchMock.mockResolvedValue(undefined);
    const { result, queryClient } = renderHookWithClient(() => useDeleteWorkspace(DELETED.id));
    const searches = [
      queryKeys.search(DELETED.id, "light"),
      queryKeys.search(DELETED.id, "glucose"),
      queryKeys.search(KEPT.id, "light"),
    ];
    for (const key of searches) {
      queryClient.setQueryData(key, searchResultsFixture(2));
    }

    await act(() => result.current.mutateAsync());

    expect(apiFetchMock).toHaveBeenCalledWith(`/workspaces/${DELETED.id}`, { method: "DELETE" });
    // Back could otherwise show the passages of a workspace that is gone.
    const cached = searches.map((key) => queryClient.getQueryData(key) !== undefined);
    expect(cached).toEqual([false, false, true]);
  });

  it("removes cached chat sessions of the deleted workspace and refreshes session lists", async () => {
    apiFetchMock.mockResolvedValue(undefined);
    const { result, queryClient } = renderHookWithClient(() => useDeleteWorkspace(DELETED.id));
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    queryClient.setQueryData(queryKeys.chatSessions(DELETED.id), { pages: [], pageParams: [] });
    queryClient.setQueryData(queryKeys.chatSessions(KEPT.id), { pages: [], pageParams: [] });
    queryClient.setQueryData(queryKeys.chatSessions(null), { pages: [], pageParams: [] });
    queryClient.setQueryData(queryKeys.chatSession("s1"), {
      id: "s1",
      workspace_id: DELETED.id,
      messages: [],
    });
    queryClient.setQueryData(queryKeys.chatSession("s2"), {
      id: "s2",
      workspace_id: KEPT.id,
      messages: [],
    });

    await act(() => result.current.mutateAsync());

    expect(queryClient.getQueryData(queryKeys.chatSessions(DELETED.id))).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.chatSessions(null))).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.chatSession("s1"))).toBeUndefined();
    expect(queryClient.getQueryData(queryKeys.chatSessions(KEPT.id))).toBeDefined();
    expect(queryClient.getQueryData(queryKeys.chatSession("s2"))).toBeDefined();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.chatSessionLists });
  });
});

describe("useUpdateWorkspace", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("invalidates chat queries so workspace_name stays current", async () => {
    apiFetchMock.mockResolvedValue({ ...DELETED, name: "Renamed" });
    const { result, queryClient } = renderHookWithClient(() => useUpdateWorkspace(DELETED.id));
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    queryClient.setQueryData(queryKeys.chatSessions(null), { pages: [], pageParams: [] });
    queryClient.setQueryData(queryKeys.chatSession("s1"), {
      id: "s1",
      workspace_id: DELETED.id,
      messages: [],
    });

    await act(() => result.current.mutateAsync({ name: "Renamed" }));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.chat });
  });
});
