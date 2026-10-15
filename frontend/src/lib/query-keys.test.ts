import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { queryKeys } from "./query-keys";

const INFINITE_KEYS: QueryKey[] = [
  queryKeys.workspaceList,
  queryKeys.workspaceDocuments("w1"),
  queryKeys.documentChunks("d1"),
];

const PLAIN_KEYS: QueryKey[] = [
  queryKeys.recentWorkspaces,
  queryKeys.workspace("w1"),
  queryKeys.document("d1"),
  queryKeys.meta,
];

function cacheWithEveryKey(): QueryClient {
  const queryClient = new QueryClient();
  for (const key of [
    ...INFINITE_KEYS,
    ...PLAIN_KEYS,
    queryKeys.workspace("w2"),
    queryKeys.workspaceDocuments("w2"),
    queryKeys.document("d2"),
    queryKeys.documentChunks("d2"),
  ]) {
    queryClient.setQueryData(key, { cached: true });
  }
  return queryClient;
}

function isCached(queryClient: QueryClient, key: QueryKey): boolean {
  return queryClient.getQueryData(key) !== undefined;
}

describe("queryKeys", () => {
  it("follows the agreed shapes", () => {
    expect(queryKeys.workspaces).toEqual(["workspaces"]);
    expect(queryKeys.workspaceList).toEqual(["workspaces", "list"]);
    expect(queryKeys.recentWorkspaces).toEqual(["workspaces", "recent"]);
    expect(queryKeys.workspace("w1")).toEqual(["workspaces", "detail", "w1"]);
    expect(queryKeys.workspaceDocuments("w1")).toEqual(["workspaces", "detail", "w1", "documents"]);
    expect(queryKeys.document("d1")).toEqual(["documents", "d1"]);
    expect(queryKeys.documentChunks("d1")).toEqual(["documents", "d1", "chunks"]);
    expect(queryKeys.meta).toEqual(["meta"]);
  });

  it("never gives an infinite list and a plain query the same key", () => {
    for (const infiniteKey of INFINITE_KEYS) {
      for (const plainKey of PLAIN_KEYS) {
        expect(infiniteKey).not.toEqual(plainKey);
      }
    }
  });

  it("lets one invalidation of the workspaces prefix refresh every workspace view", async () => {
    const queryClient = cacheWithEveryKey();

    await queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });

    const invalidated = (key: QueryKey) => queryClient.getQueryState(key)?.isInvalidated;
    expect(invalidated(queryKeys.workspaceList)).toBe(true);
    expect(invalidated(queryKeys.recentWorkspaces)).toBe(true);
    expect(invalidated(queryKeys.workspace("w1"))).toBe(true);
    expect(invalidated(queryKeys.workspaceDocuments("w1"))).toBe(true);
    expect(invalidated(queryKeys.document("d1"))).toBe(false);
    expect(invalidated(queryKeys.meta)).toBe(false);
  });

  it("drops a deleted workspace together with its document list, and nothing else", () => {
    const queryClient = cacheWithEveryKey();

    queryClient.removeQueries({ queryKey: queryKeys.workspace("w1") });

    expect(isCached(queryClient, queryKeys.workspace("w1"))).toBe(false);
    expect(isCached(queryClient, queryKeys.workspaceDocuments("w1"))).toBe(false);
    expect(isCached(queryClient, queryKeys.workspace("w2"))).toBe(true);
    expect(isCached(queryClient, queryKeys.workspaceDocuments("w2"))).toBe(true);
    expect(isCached(queryClient, queryKeys.workspaceList)).toBe(true);
  });

  it("drops a deleted document together with its chunks, and nothing else", () => {
    const queryClient = cacheWithEveryKey();

    queryClient.removeQueries({ queryKey: queryKeys.document("d1") });

    expect(isCached(queryClient, queryKeys.document("d1"))).toBe(false);
    expect(isCached(queryClient, queryKeys.documentChunks("d1"))).toBe(false);
    expect(isCached(queryClient, queryKeys.document("d2"))).toBe(true);
    expect(isCached(queryClient, queryKeys.documentChunks("d2"))).toBe(true);
  });
});
