"use client";

import { useTranslations } from "next-intl";
import { useEffect, useId, useRef } from "react";

import { Button } from "@/components/ui/button";
import type { ChunkOut, DocumentOut } from "@/lib/api/types";
import { isFocusLost, useFocusOnArrival } from "@/lib/use-focus-on-arrival";
import { cn } from "@/lib/utils";

import styles from "./chunk-list.module.css";
import { documentErrorMessage } from "./error-message";
import { useDocumentChunks } from "./hooks";

const SKELETON_ROWS = 3;

type ChunksQuery = ReturnType<typeof useDocumentChunks>;
type ChunksTranslator = ReturnType<typeof useTranslations<"Documents.chunks">>;

/** The id of a fragment's row, by the fragment's place in the document. */
function rowId(index: number): string {
  return `fragment-${index}`;
}

function pageRange(chunk: ChunkOut, t: ChunksTranslator): string | null {
  if (chunk.page_start === null) {
    return null;
  }
  const end = chunk.page_end ?? chunk.page_start;
  return end === chunk.page_start
    ? t("page", { page: chunk.page_start })
    : t("pages", { start: chunk.page_start, end });
}

interface ChunkListProps {
  document: DocumentOut;
  /** The fragment the address opens the page at, by its place in the document; null for none. */
  fragment: number | null;
  className?: string;
}

/**
 * The passages a document was cut into for search, in reading order, set in the serif of a
 * printed page. They exist only once processing has finished.
 */
export function ChunkList({ document, fragment, className }: ChunkListProps) {
  const t = useTranslations("Documents.chunks");
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const chunks = useDocumentChunks(document);
  const focusHeadingOnArrival = useFocusOnArrival(chunks.data !== undefined, headingRef);
  const { hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = chunks;
  const loadedCount = chunks.data?.chunks.length ?? 0;
  const total = chunks.data?.total ?? 0;

  // Opened at a fragment on a later page, the list loads the pages up to it, one at a time. A
  // page that fails stops it there, and Show more with its error takes over; a fragment the
  // document does not have loads nothing more. Pages kept from before a re-index still offer a
  // next page, so a document that is not ready loads nothing either.
  const isReady = document.status === "ready";
  useEffect(() => {
    if (
      isReady &&
      fragment !== null &&
      hasNextPage &&
      !isFetchingNextPage &&
      !isFetchNextPageError &&
      loadedCount <= fragment &&
      fragment < total
    ) {
      void fetchNextPage();
    }
  }, [
    isReady,
    fragment,
    hasNextPage,
    isFetchingNextPage,
    isFetchNextPageError,
    loadedCount,
    total,
    fetchNextPage,
  ]);

  function loadAgain() {
    focusHeadingOnArrival();
    void chunks.refetch();
  }

  return (
    <section aria-labelledby={headingId} className={className}>
      {/* Focusable from code only: it takes the focus when the fragments arrive in place of
          Try again. */}
      <h2
        ref={headingRef}
        id={headingId}
        tabIndex={-1}
        className="font-display w-fit text-xl font-semibold"
      >
        {t("title")}
      </h2>
      {document.status === "ready" ? (
        <ChunksBody chunks={chunks} fragment={fragment} onRetry={loadAgain} className="mt-4" />
      ) : (
        // A failed document gets fragments only if a retry succeeds, so none are promised.
        <p className="text-ink-soft mt-3 text-sm">
          {document.status === "failed" ? t("failed") : t("pending")}
        </p>
      )}
    </section>
  );
}

interface ChunksBodyProps {
  chunks: ChunksQuery;
  fragment: number | null;
  onRetry: () => void;
  className?: string;
}

function ChunksBody({ chunks, fragment, onRetry, className }: ChunksBodyProps) {
  const t = useTranslations("Documents.chunks");
  const tErrors = useTranslations("Documents.errors");

  if (chunks.data !== undefined) {
    return (
      <ChunkRows
        className={className}
        chunks={chunks.data.chunks}
        fragment={fragment}
        hasMore={chunks.hasNextPage}
        isLoadingMore={chunks.isFetchingNextPage}
        loadMoreError={
          chunks.isFetchNextPageError
            ? documentErrorMessage(chunks.error, "loadMoreFragments", tErrors)
            : null
        }
        onLoadMore={() => void chunks.fetchNextPage()}
      />
    );
  }
  if (chunks.isPending) {
    return <ChunksSkeleton className={className} />;
  }
  return (
    <div className={cn("flex flex-col items-start gap-4", className)}>
      <p role="alert" className="text-ink-soft text-sm">
        {documentErrorMessage(chunks.error, "loadFragments", tErrors)}
      </p>
      <Button variant="secondary" isLoading={chunks.isFetching} onClick={onRetry}>
        {t("retry")}
      </Button>
    </div>
  );
}

interface ChunkRowsProps {
  chunks: ChunkOut[];
  fragment: number | null;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMoreError: string | null;
  onLoadMore: () => void;
  className?: string;
}

function ChunkRows({
  chunks,
  fragment,
  hasMore,
  isLoadingMore,
  loadMoreError,
  onLoadMore,
  className,
}: ChunkRowsProps) {
  const t = useTranslations("Documents.chunks");
  const listRef = useRef<HTMLOListElement>(null);
  // Set by Show more: once the next page renders, focus moves to its first fragment, so a
  // keyboard user goes on reading from there instead of being dropped when the button goes.
  const firstNewRowRef = useRef<number | null>(null);
  // The fragment the page last went to, so that it goes to each one only once.
  const arrivedAtRef = useRef<number | null>(null);

  useEffect(() => {
    const index = firstNewRowRef.current;
    if (index === null || chunks.length <= index) {
      return;
    }
    firstNewRowRef.current = null;
    const row = listRef.current?.children[index];
    if (row instanceof HTMLElement) {
      row.focus();
    }
  }, [chunks.length]);

  // Once the fragment the address names is shown, the page goes to it: the row comes into view
  // and takes the focus, unless the user has moved the focus meanwhile. Not a layout effect:
  // Next scrolls a page it opens in a layout effect of its own, which runs after this list's and
  // would undo the scroll.
  useEffect(() => {
    if (fragment === null || arrivedAtRef.current === fragment) {
      return;
    }
    const row = listRef.current?.querySelector(`#${rowId(fragment)}`);
    if (!(row instanceof HTMLElement)) {
      return;
    }
    arrivedAtRef.current = fragment;
    if (isFocusLost()) {
      // Centred, a fragment taller than the window, as on a phone, would start above it and
      // hide its label; such a fragment is shown from its start.
      const fitsInWindow = row.offsetHeight <= window.innerHeight;
      row.scrollIntoView({ block: fitsInWindow ? "center" : "start" });
      row.focus({ preventScroll: true });
    }
  }, [fragment, chunks.length]);

  function showMore() {
    if (isLoadingMore) {
      return;
    }
    firstNewRowRef.current = chunks.length;
    onLoadMore();
  }

  return (
    <div className={className}>
      <ol ref={listRef} className="border-rule divide-rule divide-y border-y">
        {chunks.map((chunk) => (
          <ChunkRow key={chunk.id} chunk={chunk} isOpened={chunk.chunk_index === fragment} />
        ))}
      </ol>
      {hasMore ? (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
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
    </div>
  );
}

interface ChunkRowProps {
  chunk: ChunkOut;
  /** Whether the address opened the page at this fragment. */
  isOpened: boolean;
}

function ChunkRow({ chunk, isOpened }: ChunkRowProps) {
  const t = useTranslations("Documents.chunks");
  const pages = pageRange(chunk, t);

  return (
    // Focusable from code only: Show more moves the focus to the first fragment it adds, and an
    // address that names a fragment moves it there.
    <li id={rowId(chunk.chunk_index)} tabIndex={-1} className="py-5">
      {isOpened ? (
        <p className={cn(styles.opened, "mb-1 text-sm font-medium")}>{t("opened")}</p>
      ) : null}
      {chunk.heading === null && pages === null ? null : (
        <p className="text-ink-soft mb-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {chunk.heading === null ? null : (
            <span className="text-ink min-w-0 font-medium break-words">{chunk.heading}</span>
          )}
          {pages === null ? null : <span>{pages}</span>}
        </p>
      )}
      <p className="font-display text-ink max-w-[70ch] leading-7 break-words whitespace-pre-wrap">
        {chunk.content}
      </p>
    </li>
  );
}

function ChunksSkeleton({ className }: { className?: string }) {
  const t = useTranslations("Documents.chunks");
  return (
    <div aria-busy="true" className={className}>
      <span className="sr-only">{t("loading")}</span>
      <div aria-hidden className="border-rule divide-rule divide-y border-y">
        {Array.from({ length: SKELETON_ROWS }, (_, index) => (
          <div key={index} className="py-5">
            <div className="bg-ink/10 h-4 w-1/3 rounded motion-safe:animate-pulse" />
            <div className="bg-ink/10 mt-3 h-4 w-full rounded motion-safe:animate-pulse" />
            <div className="bg-ink/10 mt-2 h-4 w-5/6 rounded motion-safe:animate-pulse" />
          </div>
        ))}
      </div>
    </div>
  );
}
