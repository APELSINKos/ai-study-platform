"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, useTransition, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMeta } from "@/features/meta/hooks";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

import { SEARCH_RESULT_LIMIT } from "./api";
import { searchErrorMessage } from "./error-message";
import { useSearch } from "./hooks";
import { ResultList, SearchNotes } from "./search-results";

const SKELETON_ROWS = 2;

type SearchQuery = ReturnType<typeof useSearch>;
type SearchTranslator = ReturnType<typeof useTranslations<"Search">>;

interface SearchSectionProps {
  workspaceId: string;
  /** The search the address holds in `?q=`; null when it holds none. */
  query: string | null;
  className?: string;
}

/**
 * Search over the workspace's documents. The query lives in the address, so Back and Forward step
 * through earlier searches; the form only changes the address, and the search follows from it.
 */
export function SearchSection({ workspaceId, query, className }: SearchSectionProps) {
  const t = useTranslations("Search");
  const router = useRouter();
  const queryClient = useQueryClient();
  const headingId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const meta = useMeta().data;
  const search = useSearch(workspaceId, query);
  const [isNavigating, startTransition] = useTransition();
  const [text, setText] = useState(query ?? "");
  // The query the box was last filled from. When Back or Forward brings another one, the box
  // takes it during this render; a key would remount the box and lose the focus.
  const [shownQuery, setShownQuery] = useState(query);
  if (query !== shownQuery) {
    setShownQuery(query);
    setText(query ?? "");
  }
  const isBusy = isNavigating || search.isFetching;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // A paste can leave half of an emoji, which no address can hold.
    const next = text.trim().toWellFormed();
    if (next === "") {
      return;
    }
    if (next === query) {
      // The address already holds this search, so only a new request runs it again.
      void search.refetch();
      return;
    }
    // A search the user asks for is sent afresh, even one answered earlier: files may have
    // become ready since. Back and Forward still show the answers kept for earlier searches.
    queryClient.removeQueries({ queryKey: queryKeys.search(workspaceId, next), exact: true });
    startTransition(() =>
      router.push(`/workspaces/${workspaceId}?q=${encodeURIComponent(next)}`, { scroll: false }),
    );
  }

  // Clearing is a step in the history, like a search: Back brings the cleared search back.
  function clear() {
    setText("");
    inputRef.current?.focus();
    router.push(`/workspaces/${workspaceId}`, { scroll: false });
  }

  const status = query === null ? null : statusText(search, t);

  return (
    <section aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="font-display w-fit text-xl font-semibold">
        {t("title")}
      </h2>
      <form
        role="search"
        aria-labelledby={headingId}
        onSubmit={submit}
        className="mt-4 flex flex-wrap items-center gap-2"
      >
        <Input
          ref={inputRef}
          type="search"
          name="q"
          aria-label={t("inputLabel")}
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={meta?.search.max_query_chars}
          enterKeyHint="search"
          // On a phone the box takes a line of its own. The browser's own clear button is
          // hidden: it would empty the box and leave the search in the address.
          className="min-w-0 sm:w-auto sm:flex-1 [&::-webkit-search-cancel-button]:appearance-none"
        />
        {/* While busy it swallows clicks, and Enter with them: Enter submits a form by
            clicking its submit button. */}
        <Button type="submit" variant="secondary" isLoading={isBusy}>
          {t("submit")}
        </Button>
        {query === null ? null : (
          <Button variant="ghost" onClick={clear} aria-label={t("clearLabel")}>
            {t("clear")}
          </Button>
        )}
      </form>
      {/* The one polite live region of the search. It stays in place, empty while a search
          runs, so that each answer is announced when it arrives, with what it could not cover. */}
      <div role="status" className={cn(status !== null && "mt-4")}>
        {status === null ? null : <p className="text-ink-soft text-sm">{status}</p>}
        {status === null || search.data === undefined ? null : (
          <SearchNotes results={search.data} className="mt-3" />
        )}
      </div>
      {query === null ? null : (
        <SearchOutcome search={search} embeddingModel={meta?.ai.embedding_model ?? null} />
      )}
    </section>
  );
}

/** How many passages the last search found; null while one runs or when it failed. */
function statusText(search: SearchQuery, t: SearchTranslator): string | null {
  if (search.isFetching || search.isError || search.data === undefined) {
    return null;
  }
  const count = search.data.results.length;
  // As many as a search returns: more passages may match than are shown.
  return count === SEARCH_RESULT_LIMIT
    ? t("status.closest", { count })
    : t("status.found", { count });
}

interface SearchOutcomeProps {
  search: SearchQuery;
  embeddingModel: string | null;
}

/** Under the status line: a skeleton while the search runs, then its failure or its passages. */
function SearchOutcome({ search, embeddingModel }: SearchOutcomeProps) {
  const tErrors = useTranslations("Search.errors");

  // A search asked for again shows its skeleton too, rather than answers that are on their way out.
  if (search.isFetching || search.isPending) {
    return <ResultsSkeleton className="mt-4" />;
  }
  if (search.isError) {
    return (
      <p role="alert" className="text-ink-soft mt-4 text-sm">
        {searchErrorMessage(search.error, tErrors)}
      </p>
    );
  }
  return <ResultList hits={search.data.results} embeddingModel={embeddingModel} className="mt-4" />;
}

function ResultsSkeleton({ className }: { className?: string }) {
  const t = useTranslations("Search");
  return (
    <div aria-busy="true" className={className}>
      <span className="sr-only">{t("loading")}</span>
      <div aria-hidden className="border-rule divide-rule divide-y border-y">
        {Array.from({ length: SKELETON_ROWS }, (_, index) => (
          <div key={index} className="py-4">
            <div className="bg-ink/10 h-5 w-1/3 rounded motion-safe:animate-pulse" />
            <div className="bg-ink/10 mt-3 h-4 w-full rounded motion-safe:animate-pulse" />
            <div className="bg-ink/10 mt-2 h-4 w-4/5 rounded motion-safe:animate-pulse" />
          </div>
        ))}
      </div>
    </div>
  );
}
