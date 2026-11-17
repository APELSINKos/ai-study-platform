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
  queryKeys.search("w1", "light"),
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
    queryKeys.search("w1", "dark"),
    queryKeys.search("w2", "light"),
  ]) {
    queryClient.setQueryData(key, { cached: true });
  }
  return queryClient;
}

function isCached(queryClient: QueryClient, key: QueryKey): boolean {
  return queryClient.getQueryData(key) !== undefined;
}

function isInvalidated(queryClient: QueryClient, key: QueryKey): boolean | undefined {
  return queryClient.getQueryState(key)?.isInvalidated;
}

describe("queryKeys", () => {
  it("follows the agreed shapes", () => {
    expect(queryKeys.workspaces).toEqual(["workspaces"]);
    expect(queryKeys.workspaceList).toEqual(["workspaces", "list"]);
    expect(queryKeys.recentWorkspaces).toEqual(["workspaces", "recent"]);
    expect(queryKeys.workspace("w1")).toEqual(["workspaces", "detail", "w1"]);
    expect(queryKeys.workspaceDocuments("w1")).toEqual(["workspaces", "detail", "w1", "documents"]);
    expect(queryKeys.documents).toEqual(["documents"]);
    expect(queryKeys.document("d1")).toEqual(["documents", "d1"]);
    expect(queryKeys.documentChunks("d1")).toEqual(["documents", "d1", "chunks"]);
    expect(queryKeys.workspaceSearches("w1")).toEqual(["search", "w1"]);
    expect(queryKeys.search("w1", "light")).toEqual(["search", "w1", "light"]);
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

    expect(isInvalidated(queryClient, queryKeys.workspaceList)).toBe(true);
    expect(isInvalidated(queryClient, queryKeys.recentWorkspaces)).toBe(true);
    expect(isInvalidated(queryClient, queryKeys.workspace("w1"))).toBe(true);
    expect(isInvalidated(queryClient, queryKeys.workspaceDocuments("w1"))).toBe(true);
    expect(isInvalidated(queryClient, queryKeys.document("d1"))).toBe(false);
    expect(isInvalidated(queryClient, queryKeys.meta)).toBe(false);
    // Uploads and retries invalidate the workspaces, never the searches.
    expect(isInvalidated(queryClient, queryKeys.search("w1", "light"))).toBe(false);
  });

  it("lets one invalidation reach every search of a workspace, and no other", async () => {
    const queryClient = cacheWithEveryKey();

    await queryClient.invalidateQueries({ queryKey: queryKeys.workspaceSearches("w1") });

    expect(isInvalidated(queryClient, queryKeys.search("w1", "light"))).toBe(true);
    expect(isInvalidated(queryClient, queryKeys.search("w1", "dark"))).toBe(true);
    expect(isInvalidated(queryClient, queryKeys.search("w2", "light"))).toBe(false);
    expect(isInvalidated(queryClient, queryKeys.workspace("w1"))).toBe(false);
    expect(isInvalidated(queryClient, queryKeys.workspaceDocuments("w1"))).toBe(false);
  });

  it("drops a deleted workspace together with its document list, and nothing else", () => {
    const queryClient = cacheWithEveryKey();

    queryClient.removeQueries({ queryKey: queryKeys.workspace("w1") });

    expect(isCached(queryClient, queryKeys.workspace("w1"))).toBe(false);
    expect(isCached(queryClient, queryKeys.workspaceDocuments("w1"))).toBe(false);
    expect(isCached(queryClient, queryKeys.workspace("w2"))).toBe(true);
    expect(isCached(queryClient, queryKeys.workspaceDocuments("w2"))).toBe(true);
    expect(isCached(queryClient, queryKeys.workspaceList)).toBe(true);
    // The searches sit apart, so the delete removes them by their own prefix.
    expect(isCached(queryClient, queryKeys.search("w1", "light"))).toBe(true);
  });

  it("drops the searches of one workspace, and nothing else", () => {
    const queryClient = cacheWithEveryKey();

    queryClient.removeQueries({ queryKey: queryKeys.workspaceSearches("w1") });

    expect(isCached(queryClient, queryKeys.search("w1", "light"))).toBe(false);
    expect(isCached(queryClient, queryKeys.search("w1", "dark"))).toBe(false);
    expect(isCached(queryClient, queryKeys.search("w2", "light"))).toBe(true);
    expect(isCached(queryClient, queryKeys.workspace("w1"))).toBe(true);
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
