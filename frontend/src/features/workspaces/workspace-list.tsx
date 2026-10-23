"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { IndexCard } from "@/components/ui/index-card";
import type { WorkspaceOut } from "@/lib/api/types";
import { useFocusOnArrival } from "@/lib/use-focus-on-arrival";
import { cn } from "@/lib/utils";

import { CreateWorkspaceForm } from "./create-workspace-form";
import { workspaceErrorMessage } from "./error-message";
import { useWorkspaceList } from "./hooks";
import { WorkspaceRow } from "./workspace-row";

const SKELETON_ROWS = 3;

type WorkspaceListQuery = ReturnType<typeof useWorkspaceList>;

/**
 * The workspaces page: every workspace of the user as ruled rows of one index card. With none
 * yet, the create form is the page; otherwise New workspace opens it above the list.
 */
export function WorkspaceList({ startWithForm = false }: { startWithForm?: boolean }) {
  const t = useTranslations("Workspaces");
  const list = useWorkspaceList();
  const [isFormOpen, setIsFormOpen] = useState(startWithForm);
  // Set by Cancel, so that New workspace takes the focus back when it reappears.
  const returnFocusRef = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusHeadingOnArrival = useFocusOnArrival(list.data !== undefined, headingRef);

  const isEmpty = list.data?.length === 0;
  const showForm = isFormOpen || isEmpty;

  function closeForm() {
    returnFocusRef.current = true;
    setIsFormOpen(false);
  }

  function takeReturningFocus(button: HTMLButtonElement | null) {
    if (button && returnFocusRef.current) {
      returnFocusRef.current = false;
      button.focus();
    }
  }

  function loadAgain() {
    focusHeadingOnArrival();
    void list.refetch();
  }

  return (
    <div className="notebook-row">
      <p className="margin-note">{t("marginNote")}</p>
      {/* The title row, the form and the list share one width, so their right edges line up. */}
      <div className="max-w-3xl">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
          {/* Focusable from code only: it takes the focus when the list arrives in place of
              Try again. */}
          <h1 ref={headingRef} tabIndex={-1} className="font-display text-title font-semibold">
            {t("title")}
          </h1>
          {showForm || list.isPending ? null : (
            <Button ref={takeReturningFocus} variant="primary" onClick={() => setIsFormOpen(true)}>
              {t("newWorkspace")}
            </Button>
          )}
        </div>
        {isEmpty ? (
          <p className="text-ink-soft mt-4 max-w-[58ch] text-lg leading-8">{t("emptyLead")}</p>
        ) : null}
        {showForm ? (
          <CreateWorkspaceForm
            className="mt-8"
            autoFocus={isFormOpen}
            onCancel={isEmpty ? undefined : closeForm}
          />
        ) : null}
        <ListBody list={list} onRetry={loadAgain} className="mt-8" />
      </div>
    </div>
  );
}

interface ListBodyProps {
  list: WorkspaceListQuery;
  onRetry: () => void;
  className?: string;
}

function ListBody({ list, onRetry, className }: ListBodyProps) {
  const t = useTranslations("Workspaces.list");
  const tErrors = useTranslations("Workspaces.errors");

  if (list.isPending) {
    return <ListSkeleton className={className} />;
  }
  // Rows already shown stay when a later request fails; only a list with nothing to show
  // turns into the error.
  if (list.data === undefined) {
    return (
      <div className={cn("flex flex-col items-start gap-4", className)}>
        <p role="alert" className="text-ink-soft text-sm">
          {workspaceErrorMessage(list.error, "load", tErrors)}
        </p>
        <Button variant="secondary" isLoading={list.isFetching} onClick={onRetry}>
          {t("retry")}
        </Button>
      </div>
    );
  }
  if (list.data.length === 0) {
    return null;
  }
  return (
    <WorkspaceRows
      className={className}
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
  className?: string;
}

function WorkspaceRows({
  workspaces,
  hasMore,
  isLoadingMore,
  loadMoreError,
  onLoadMore,
  className,
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
    <IndexCard className={cn("overflow-hidden", className)}>
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

function ListSkeleton({ className }: { className?: string }) {
  const t = useTranslations("Workspaces.list");
  return (
    <IndexCard aria-busy="true" className={className}>
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
