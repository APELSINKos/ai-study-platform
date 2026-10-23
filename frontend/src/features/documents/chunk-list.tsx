"use client";

import { useTranslations } from "next-intl";
import { useEffect, useId, useRef } from "react";

import { Button } from "@/components/ui/button";
import type { ChunkOut, DocumentOut } from "@/lib/api/types";
import { useFocusOnArrival } from "@/lib/use-focus-on-arrival";
import { cn } from "@/lib/utils";

import { documentErrorMessage } from "./error-message";
import { useDocumentChunks } from "./hooks";

const SKELETON_ROWS = 3;

type ChunksQuery = ReturnType<typeof useDocumentChunks>;
type ChunksTranslator = ReturnType<typeof useTranslations<"Documents.chunks">>;

function pageRange(chunk: ChunkOut, t: ChunksTranslator): string | null {
  if (chunk.page_start === null) {
    return null;
  }
  const end = chunk.page_end ?? chunk.page_start;
  return end === chunk.page_start
    ? t("page", { page: chunk.page_start })
    : t("pages", { start: chunk.page_start, end });
}

/**
 * The passages a document was cut into for search, in reading order, set in the serif of a
 * printed page. They exist only once processing has finished.
 */
export function ChunkList({ document, className }: { document: DocumentOut; className?: string }) {
  const t = useTranslations("Documents.chunks");
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const chunks = useDocumentChunks(document);
  const focusHeadingOnArrival = useFocusOnArrival(chunks.data !== undefined, headingRef);

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
        <ChunksBody chunks={chunks} onRetry={loadAgain} className="mt-4" />
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
  onRetry: () => void;
  className?: string;
}

function ChunksBody({ chunks, onRetry, className }: ChunksBodyProps) {
  const t = useTranslations("Documents.chunks");
  const tErrors = useTranslations("Documents.errors");

  if (chunks.data !== undefined) {
    return (
      <ChunkRows
        className={className}
        chunks={chunks.data}
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
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMoreError: string | null;
  onLoadMore: () => void;
  className?: string;
}

function ChunkRows({
  chunks,
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
          <ChunkRow key={chunk.id} chunk={chunk} />
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

function ChunkRow({ chunk }: { chunk: ChunkOut }) {
  const t = useTranslations("Documents.chunks");
  const pages = pageRange(chunk, t);

  return (
    // Focusable from code only: Show more moves the focus to the first fragment it adds.
    <li tabIndex={-1} className="py-5">
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
