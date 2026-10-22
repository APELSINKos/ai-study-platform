"use client";

import { ArrowClockwiseIcon, TrashIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useId, useRef, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import { useWorkspace } from "@/features/workspaces/hooks";
import { ApiError, isClientError } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

import { ChunkList } from "./chunk-list";
import { DeleteDocumentDialog, RetryProcessingButton } from "./document-actions";
import { DocumentFacts } from "./document-facts";
import { StageLine } from "./document-row";
import { DownloadButton } from "./download-button";
import {
  DOCUMENT_NOT_FOUND_CODE,
  documentErrorMessage,
  processingErrorMessage,
} from "./error-message";
import { useDeleteDocument, useDocument } from "./hooks";
import { documentProgress } from "./status";

// A malformed id fails validation before the backend looks for a document.
const MISSING_DOCUMENT_CODES: ReadonlySet<string> = new Set([
  DOCUMENT_NOT_FOUND_CODE,
  "validation_error",
]);
// Holds the margin note's line while the workspace's name is on its way.
const RESERVED_LINE = " ";

function isMissingDocument(error: unknown): boolean {
  return error instanceof ApiError && MISSING_DOCUMENT_CODES.has(error.code);
}

/** The page of one document, fetched in the browser: the server never sees the session. */
export function DocumentView({ id }: { id: string }) {
  const query = useDocument(id);

  if (isMissingDocument(query.error)) {
    return <DocumentNotFound />;
  }
  // Checked before the data: a refused request stops the polling, so a cached copy shown as on
  // its way would never move on.
  const document = isClientError(query.error) ? undefined : query.data;
  if (document !== undefined) {
    return <DocumentDetail document={document} />;
  }
  if (query.isPending) {
    return <DocumentSkeleton />;
  }
  return (
    <DocumentLoadError
      error={query.error}
      isRetrying={query.isFetching}
      onRetry={() => void query.refetch()}
    />
  );
}

function DocumentDetail({ document }: { document: DocumentOut }) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  return (
    <div className="notebook-row">
      <WorkspaceCrumb workspaceId={document.workspace_id} />
      <div className="max-w-3xl">
        <DocumentHeader document={document} headingRef={headingRef} />
        <ProcessingState document={document} className="mt-4" />
        <DocumentActions
          document={document}
          onRetried={() => headingRef.current?.focus()}
          className="mt-5"
        />
        <DocumentAnalysis document={document} />
        <ChunkList document={document} className="mt-12" />
      </div>
    </div>
  );
}

/** The margin names the workspace the document belongs to, as the way back to it. */
function WorkspaceCrumb({ workspaceId }: { workspaceId: string }) {
  const t = useTranslations("Documents.detail");
  const workspace = useWorkspace(workspaceId);

  return (
    <nav aria-label={t("breadcrumb")} className="margin-note">
      {workspace.isPending ? (
        RESERVED_LINE
      ) : (
        // The padding keeps the underline of the last line inside the clamped box.
        <Link
          href={`/workspaces/${workspaceId}`}
          className="decoration-pen/50 hover:decoration-pen line-clamp-3 pb-1 break-words underline underline-offset-4"
        >
          {workspace.data?.name ?? t("workspace")}
        </Link>
      )}
    </nav>
  );
}

interface DocumentHeaderProps {
  document: DocumentOut;
  headingRef: RefObject<HTMLHeadingElement | null>;
}

function DocumentHeader({ document, headingRef }: DocumentHeaderProps) {
  const locale = useLocale();
  return (
    <>
      {/* Focusable from code only: it takes the focus when Retry goes away. */}
      <h1
        ref={headingRef}
        tabIndex={-1}
        className="font-display text-title w-fit max-w-full font-semibold break-words"
      >
        {document.title ?? document.original_filename}
      </h1>
      <p className="text-ink-soft mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {document.title === null ? null : (
          <span title={document.original_filename} className="max-w-full truncate">
            {document.original_filename}
          </span>
        )}
        <span>{formatBytes(document.size_bytes, locale)}</span>
      </p>
    </>
  );
}

/** Where processing stands, in words beside the rail: the page's one live region. */
function ProcessingState({ document, className }: { document: DocumentOut; className?: string }) {
  const tRow = useTranslations("Documents.row");
  const tErrors = useTranslations("Documents.processingErrors");
  const progress = documentProgress(document);

  return (
    <div role="status" className={cn("flex flex-col gap-1.5", className)}>
      <StageLine status={document.status} progress={progress} />
      {progress.kind === "failed" ? (
        <p className="text-margin text-sm">{processingErrorMessage(progress.errorCode, tErrors)}</p>
      ) : null}
      {progress.kind === "active" && progress.note === "stalled" ? (
        <p className="text-ink-soft text-sm">{tRow("stalled")}</p>
      ) : null}
    </div>
  );
}

interface DocumentActionsProps {
  document: DocumentOut;
  /** Runs once a retry has put the document back on its way, which takes Retry away. */
  onRetried: () => void;
  className?: string;
}

/**
 * What can be done with the document, none of it the page's main action. A failure shows under
 * the buttons, apart from that of a delete, which the dialog shows.
 */
function DocumentActions({ document, onRetried, className }: DocumentActionsProps) {
  const t = useTranslations("Documents.detail");
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {document.can_retry ? (
        <RetryProcessingButton
          document={document}
          label={t("retryProcessing")}
          icon={<ArrowClockwiseIcon aria-hidden />}
          onRetried={onRetried}
        />
      ) : null}
      <DownloadButton document={document} />
      <DeleteDocumentButton document={document} />
    </div>
  );
}

function DeleteDocumentButton({ document }: { document: DocumentOut }) {
  const t = useTranslations("Documents.detail");
  const router = useRouter();
  const deletion = useDeleteDocument(document);

  function deleteAndLeave() {
    return deletion.mutateAsync(undefined, {
      // A callback passed here runs only while the page is still mounted, so a user who has left
      // meanwhile stays where they went. Replaced, so that Back does not return to the page of a
      // document that is gone.
      onSuccess: () => router.replace(`/workspaces/${document.workspace_id}`),
    });
  }

  return (
    <DeleteDocumentDialog
      document={document}
      trigger={
        <Button variant="danger" size="sm">
          <TrashIcon aria-hidden />
          {t("delete")}
        </Button>
      }
      onConfirm={deleteAndLeave}
    />
  );
}

/** The summary, the topics and the facts, as far as processing has got with them. */
function DocumentAnalysis({ document }: { document: DocumentOut }) {
  const topics = document.topics ?? [];
  return (
    <>
      {document.summary === null ? null : (
        <p className="text-ink mt-10 max-w-[65ch] text-lg leading-8 break-words">
          {document.summary}
        </p>
      )}
      {topics.length > 0 ? <Topics topics={topics} className="mt-8" /> : null}
      <DocumentFacts document={document} className="mt-10" />
    </>
  );
}

/** The topics as one line of items, the way a paper lists its keywords under the abstract. */
function Topics({ topics, className }: { topics: readonly string[]; className?: string }) {
  const t = useTranslations("Documents.detail");
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="font-display text-xl font-semibold">
        {t("topicsTitle")}
      </h2>
      <ul className="text-ink mt-3 flex flex-wrap gap-x-1.5 gap-y-1 leading-7">
        {topics.map((topic) => (
          <li key={topic} className="min-w-0 break-words not-last:after:content-[',']">
            {topic}
          </li>
        ))}
      </ul>
    </section>
  );
}

function DocumentSkeleton() {
  const t = useTranslations("Documents.detail");
  return (
    <div className="notebook-row">
      <div aria-busy="true" className="max-w-3xl">
        <h1 className="sr-only">{t("metaTitle")}</h1>
        <p className="sr-only">{t("loading")}</p>
        <div aria-hidden>
          <div className="bg-ink/10 h-10 w-80 max-w-full rounded motion-safe:animate-pulse" />
          <div className="bg-ink/10 mt-4 h-4 w-48 max-w-full rounded motion-safe:animate-pulse" />
          <div className="bg-ink/10 mt-10 h-5 w-full max-w-xl rounded motion-safe:animate-pulse" />
          <div className="bg-ink/10 mt-3 h-5 w-full max-w-lg rounded motion-safe:animate-pulse" />
        </div>
      </div>
    </div>
  );
}

function DocumentNotFound() {
  const t = useTranslations("Documents.detail.notFound");
  return (
    <div className="notebook-row">
      <div className="max-w-3xl">
        <h1 className="font-display text-title font-semibold">{t("title")}</h1>
        <p className="text-ink-soft mt-4 max-w-[58ch] text-lg leading-8">{t("lead")}</p>
        <Button asChild variant="primary" className="mt-8">
          <Link href="/workspaces">{t("back")}</Link>
        </Button>
      </div>
    </div>
  );
}

interface DocumentLoadErrorProps {
  error: unknown;
  isRetrying: boolean;
  onRetry: () => void;
}

function DocumentLoadError({ error, isRetrying, onRetry }: DocumentLoadErrorProps) {
  const t = useTranslations("Documents.detail");
  const tErrors = useTranslations("Documents.errors");
  return (
    <div className="notebook-row">
      <div className="flex max-w-3xl flex-col items-start gap-4">
        <h1 className="sr-only">{t("metaTitle")}</h1>
        <p role="alert" className="text-ink-soft">
          {documentErrorMessage(error, "open", tErrors)}
        </p>
        <Button variant="secondary" isLoading={isRetrying} onClick={onRetry}>
          {t("retry")}
        </Button>
      </div>
    </div>
  );
}
