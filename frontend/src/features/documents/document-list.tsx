"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import { IndexCard } from "@/components/ui/index-card";
import { isClientError } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { DocumentRow } from "./document-row";
import { documentErrorMessage } from "./error-message";
import { useWorkspaceDocuments, type LoadedDocuments } from "./hooks";
import { tallyDocuments } from "./status";

const SKELETON_ROWS = 3;

type DocumentListQuery = ReturnType<typeof useWorkspaceDocuments>;
type DocumentsTranslator = ReturnType<typeof useTranslations<"Documents">>;

interface DocumentListProps {
  workspaceId: string;
  /** The list's heading, which takes the focus when a deleted document's row goes. */
  headingRef: RefObject<HTMLElement | null>;
  className?: string;
}

/**
 * The documents of a workspace as ruled rows of one index card, under a line that sums up their
 * processing. The list asks for fresh statuses while any document is on its way.
 */
export function DocumentList({ workspaceId, headingRef, className }: DocumentListProps) {
  const list = useWorkspaceDocuments(workspaceId);
  // Checked before the data: after a refused request the cached rows are no longer refreshed,
  // so a document shown as processing would never move on.
  const loaded = isClientError(list.error) ? undefined : list.data;

  return (
    <div className={className}>
      <ListSummary loaded={loaded} />
      <ListBody
        list={list}
        documents={loaded?.documents}
        headingRef={headingRef}
        className="mt-6"
      />
    </div>
  );
}

/** The one polite live region of the list, so a change of status is announced once. */
function ListSummary({ loaded }: { loaded: LoadedDocuments | undefined }) {
  const t = useTranslations("Documents");
  return (
    <p role="status" className="text-ink-soft text-sm">
      {loaded === undefined ? null : summaryText(loaded, t)}
    </p>
  );
}

/**
 * Counts the loaded rows only. The statuses of documents on pages not loaded yet are unknown, so
 * with more documents than loaded the summary first says how many it counts.
 */
function summaryText({ documents, total }: LoadedDocuments, t: DocumentsTranslator): string {
  if (total === 0) {
    return t("list.empty");
  }
  const shown = documents.length;
  const { active, ready, failed } = tallyDocuments(documents);
  const sentences: string[] = [];
  if (shown < total) {
    sentences.push(t("summary.shown", { shown, total }));
  }
  if (active > 0) {
    sentences.push(t("summary.processing", { active, total: shown }));
  } else if (ready > 0 && ready === shown) {
    sentences.push(t("summary.allReady", { total: shown }));
  } else if (ready > 0) {
    sentences.push(t("summary.someReady", { ready, total: shown }));
  }
  if (failed > 0) {
    sentences.push(t("summary.failed", { failed }));
  }
  return sentences.join(" ");
}

interface ListBodyProps {
  list: DocumentListQuery;
  documents: DocumentOut[] | undefined;
  headingRef: RefObject<HTMLElement | null>;
  className?: string;
}

function ListBody({ list, documents, headingRef, className }: ListBodyProps) {
  const t = useTranslations("Documents.list");
  const tErrors = useTranslations("Documents.errors");

  if (documents !== undefined) {
    if (documents.length === 0) {
      return null;
    }
    return (
      <DocumentRows
        className={className}
        documents={documents}
        headingRef={headingRef}
        hasMore={list.hasNextPage}
        isLoadingMore={list.isFetchingNextPage}
        loadMoreError={
          list.isFetchNextPageError ? documentErrorMessage(list.error, "loadMore", tErrors) : null
        }
        onLoadMore={() => void list.fetchNextPage()}
      />
    );
  }
  if (list.isPending) {
    return <ListSkeleton className={className} />;
  }
  return (
    <div className={cn("flex flex-col items-start gap-4", className)}>
      <p role="alert" className="text-ink-soft text-sm">
        {documentErrorMessage(list.error, "load", tErrors)}
      </p>
      <Button variant="secondary" isLoading={list.isFetching} onClick={() => void list.refetch()}>
        {t("retry")}
      </Button>
    </div>
  );
}

interface DocumentRowsProps {
  documents: DocumentOut[];
  headingRef: RefObject<HTMLElement | null>;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMoreError: string | null;
  onLoadMore: () => void;
  className?: string;
}

function DocumentRows({
  documents,
  headingRef,
  hasMore,
  isLoadingMore,
  loadMoreError,
  onLoadMore,
  className,
}: DocumentRowsProps) {
  const t = useTranslations("Documents.list");
  const listRef = useRef<HTMLUListElement>(null);
  // Set by Show more: once the next page renders, focus moves to its first document, so a
  // keyboard user goes on reading from there instead of being dropped when the button goes.
  const firstNewRowRef = useRef<number | null>(null);

  useEffect(() => {
    const index = firstNewRowRef.current;
    if (index === null || documents.length <= index) {
      return;
    }
    firstNewRowRef.current = null;
    listRef.current?.children[index]?.querySelector("a")?.focus();
  }, [documents.length]);

  function showMore() {
    if (isLoadingMore) {
      return;
    }
    firstNewRowRef.current = documents.length;
    onLoadMore();
  }

  return (
    <IndexCard className={cn("overflow-hidden", className)}>
      <ul ref={listRef} aria-label={t("label")} className="divide-rule divide-y">
        {documents.map((document) => (
          <DocumentRow key={document.id} document={document} focusAfterDelete={headingRef} />
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
  const t = useTranslations("Documents.list");
  return (
    <IndexCard aria-busy="true" className={className}>
      <span className="sr-only">{t("loading")}</span>
      <div aria-hidden className="divide-rule divide-y">
        {Array.from({ length: SKELETON_ROWS }, (_, index) => (
          <div key={index} className="flex gap-3 px-5 py-4 sm:gap-4 sm:px-6">
            <div className="bg-paper size-5 shrink-0 rounded motion-safe:animate-pulse" />
            <div className="min-w-0 flex-1">
              <div className="bg-paper h-5 w-1/2 rounded motion-safe:animate-pulse" />
              <div className="bg-paper mt-2 h-4 w-1/3 rounded motion-safe:animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    </IndexCard>
  );
}
