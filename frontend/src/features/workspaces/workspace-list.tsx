"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { IndexCard } from "@/components/ui/index-card";
import type { WorkspaceOut } from "@/lib/api/types";

import { workspaceErrorMessage } from "./error-message";
import { useWorkspaceList } from "./hooks";
import { WorkspaceRow } from "./workspace-row";

const SKELETON_ROWS = 3;

type WorkspaceListQuery = ReturnType<typeof useWorkspaceList>;

/** The workspaces page: every workspace of the user as ruled rows of one index card. */
export function WorkspaceList() {
  const t = useTranslations("Workspaces");
  const list = useWorkspaceList();

  return (
    <div className="notebook-row">
      <p className="margin-note">{t("marginNote")}</p>
      <div>
        <h1 className="font-display text-title font-semibold">{t("title")}</h1>
        <div className="mt-8">
          <ListBody list={list} />
        </div>
      </div>
    </div>
  );
}

function ListBody({ list }: { list: WorkspaceListQuery }) {
  const t = useTranslations("Workspaces.list");
  const tErrors = useTranslations("Workspaces.errors");

  if (list.isPending) {
    return <ListSkeleton />;
  }
  // Rows already shown stay when a later request fails; only a list with nothing to show
  // turns into the error.
  if (list.data === undefined) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p role="alert" className="text-ink-soft text-sm">
          {workspaceErrorMessage(list.error, "load", tErrors)}
        </p>
        <Button variant="secondary" isLoading={list.isFetching} onClick={() => void list.refetch()}>
          {t("retry")}
        </Button>
      </div>
    );
  }
  if (list.data.length === 0) {
    return <p className="text-ink-soft max-w-[58ch] text-lg leading-8">{t("empty")}</p>;
  }
  return (
    <WorkspaceRows
      workspaces={list.data}
      hasMore={list.hasNextPage}
      isLoadingMore={list.isFetchingNextPage}
      loadMoreError={
        list.isFetchNextPageError ? workspaceErrorMessage(list.error, "loadMore", tErrors) : null
      }
      onLoadMore={() => void list.fetchNextPage()}
    />
  );
}

interface WorkspaceRowsProps {
  workspaces: WorkspaceOut[];
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMoreError: string | null;
  onLoadMore: () => void;
}

function WorkspaceRows({
  workspaces,
  hasMore,
  isLoadingMore,
  loadMoreError,
  onLoadMore,
}: WorkspaceRowsProps) {
  const t = useTranslations("Workspaces.list");
  const listRef = useRef<HTMLUListElement>(null);
  // Set by Show more: once the next page renders, focus moves to its first workspace, so a
  // keyboard user goes on reading from there instead of being dropped when the button goes.
  const firstNewRowRef = useRef<number | null>(null);

  useEffect(() => {
    const index = firstNewRowRef.current;
    if (index === null || workspaces.length <= index) {
      return;
    }
    firstNewRowRef.current = null;
    listRef.current?.children[index]?.querySelector("a")?.focus();
  }, [workspaces.length]);

  function showMore() {
    if (isLoadingMore) {
      return;
    }
    firstNewRowRef.current = workspaces.length;
    onLoadMore();
  }

  return (
    <IndexCard className="overflow-hidden">
      <ul ref={listRef} aria-label={t("label")} className="divide-rule divide-y">
        {workspaces.map((workspace) => (
          <WorkspaceRow key={workspace.id} workspace={workspace} />
        ))}
      </ul>
      {hasMore ? (
        <div className="border-rule flex flex-wrap items-center gap-x-4 gap-y-2 border-t px-5 py-3 sm:px-6">
          <Button variant="secondary" size="sm" isLoading={isLoadingMore} onClick={showMore}>
            {t("showMore")}
          </Button>
          {loadMoreError ? (
            <p role="alert" className="text-margin text-sm">
              {loadMoreError}
            </p>
          ) : null}
        </div>
      ) : null}
    </IndexCard>
  );
}

function ListSkeleton() {
  const t = useTranslations("Workspaces.list");
  return (
    <IndexCard aria-busy="true">
      <span className="sr-only">{t("loading")}</span>
      <div aria-hidden className="divide-rule divide-y">
        {Array.from({ length: SKELETON_ROWS }, (_, index) => (
          <div key={index} className="px-5 py-4 sm:px-6">
            <div className="bg-paper h-5 w-1/2 animate-pulse rounded" />
            <div className="bg-paper mt-3 h-4 w-1/3 animate-pulse rounded" />
          </div>
        ))}
      </div>
    </IndexCard>
  );
}
