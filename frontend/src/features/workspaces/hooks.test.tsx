import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { searchResultsFixture } from "@/features/search/test-fixtures";
import { apiFetch } from "@/lib/api/client";
import { queryKeys } from "@/lib/query-keys";

import { useDeleteWorkspace } from "./hooks";
import { workspaceFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const DELETED = workspaceFixture(1);
const KEPT = workspaceFixture(2);

function renderDelete(id: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { ...renderHook(() => useDeleteWorkspace(id), { wrapper: Wrapper }), queryClient };
}

describe("useDeleteWorkspace", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("forgets the searches of the deleted workspace, and only those", async () => {
    apiFetchMock.mockResolvedValue(undefined);
    const { result, queryClient } = renderDelete(DELETED.id);
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
});
