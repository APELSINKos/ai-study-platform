"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Snippet } from "@/components/snippet";
import { passageHref } from "@/features/documents/passage-href";
import { headingBelowTitle, pageRange } from "@/features/documents/passage-meta";
import { isBuiltInModel } from "@/features/meta/models";
import type { MatchKind, SearchHit, SearchResults } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type RowTranslator = ReturnType<typeof useTranslations<"Search.row">>;

/**
 * The name of a passage's link: the document's title, then what tells the passage apart from the
 * other passages of that document. Several can share a page or a heading, but each has a place of
 * its own in the document.
 */
function linkName(
  hit: SearchHit,
  heading: string | null,
  pages: string | null,
  t: RowTranslator,
): string {
  const parts = [hit.document_title, pages, heading, t("passage", { number: hit.chunk_index + 1 })];
  return parts.filter((part) => part !== null).join(", ");
}

/** What a search could not cover, or covered only by its words; nothing when it covered all. */
export function SearchNotes({
  results,
  className,
}: {
  results: SearchResults;
  className?: string;
}) {
  const t = useTranslations("Search.notes");
  const notes: string[] = [];
  if (results.searched_document_count === 0) {
    notes.push(t("noReady"));
  }
  if (results.pending_document_count > 0) {
    notes.push(t("pending", { count: results.pending_document_count }));
  }
  if (results.stale_document_count > 0) {
    notes.push(t("stale", { count: results.stale_document_count }));
  }
  // When every ready file was indexed with another model, the note above already says why.
  if (
    !results.semantic_available &&
    results.searched_document_count > results.stale_document_count
  ) {
    notes.push(t("wordsOnly"));
  }

  if (notes.length === 0) {
    return null;
  }
  return (
    <div className={cn("border-rule-strong flex flex-col gap-1 border-l-2 pl-3", className)}>
      {notes.map((note) => (
        <p key={note} className="text-ink-soft text-sm">
          {note}
        </p>
      ))}
    </div>
  );
}

interface ResultListProps {
  hits: SearchHit[];
  /** The model that embedded the passages and the query, from /meta; null while not known. */
  embeddingModel: string | null;
  className?: string;
}

/** The passages a search found, the best first, as ruled rows that open each one in its document. */
export function ResultList({ hits, embeddingModel, className }: ResultListProps) {
  const t = useTranslations("Search");
  if (hits.length === 0) {
    return null;
  }
  // The built-in embeddings compare words and their beginnings, not meaning, so only a real
  // model, once /meta has named it, earns the word.
  const comparesMeaning = embeddingModel !== null && !isBuiltInModel(embeddingModel);
  const labels = {
    keyword: t("match.keyword"),
    semantic: comparesMeaning ? t("match.meaning") : t("match.words"),
  } satisfies Record<MatchKind, string>;

  return (
    <ol
      aria-label={t("resultsLabel")}
      className={cn("border-rule divide-rule divide-y border-y", className)}
    >
      {hits.map((hit) => (
        <ResultRow key={hit.chunk_id} hit={hit} labels={labels} />
      ))}
    </ol>
  );
}

interface ResultRowProps {
  hit: SearchHit;
  /** What to call each way a passage can be found. */
  labels: Record<MatchKind, string>;
}

/**
 * One passage: the document's title is the link, stretched over the whole row. Only the title
 * shows; the link's name adds where the passage is, for the list of links a screen reader offers.
 */
function ResultRow({ hit, labels }: ResultRowProps) {
  const t = useTranslations("Search.row");
  const heading = headingBelowTitle(hit);
  const pages = pageRange(hit, {
    page: (page) => t("page", { page }),
    pages: (start, end) => t("pages", { start, end }),
  });

  return (
    <li className="group relative py-4">
      <Link
        href={passageHref(hit.document_id, hit.chunk_index)}
        aria-label={linkName(hit, heading, pages, t)}
        className="text-ink focus-visible:after:outline-pen font-medium break-words group-hover:underline after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-offset-2 focus-visible:after:outline-solid"
      >
        {hit.document_title}
      </Link>
      {heading === null && pages === null ? null : (
        <p className="text-ink-soft mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {heading === null ? null : <span className="min-w-0 break-words">{heading}</span>}
          {pages === null ? null : <span>{pages}</span>}
        </p>
      )}
      <p className="font-display text-ink mt-2 max-w-[70ch] leading-7 break-words">
        <Snippet parts={hit.snippet} />
      </p>
      <p className="text-ink-soft mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {hit.matched_by.map((kind) => (
          <span key={kind}>{labels[kind]}</span>
        ))}
      </p>
    </li>
  );
}
