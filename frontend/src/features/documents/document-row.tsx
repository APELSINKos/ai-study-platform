"use client";

import { FileMdIcon, FilePdfIcon, FileTxtIcon, TrashIcon, type Icon } from "@phosphor-icons/react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useRef, type ReactNode, type RefObject } from "react";

import { AlertDialog } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import type { DocumentContentType, DocumentOut } from "@/lib/api/types";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

import { documentErrorMessage, processingErrorMessage } from "./error-message";
import { useDeleteDocument, useRetryDocument } from "./hooks";
import { documentProgress, type DocumentProgress } from "./status";
import { StatusRail } from "./status-rail";

const FILE_ICONS = {
  "application/pdf": FilePdfIcon,
  "text/markdown": FileMdIcon,
  "text/plain": FileTxtIcon,
} as const satisfies Record<DocumentContentType, Icon>;

interface DocumentRowProps {
  document: DocumentOut;
  /** Takes the focus once the document is deleted, since the row and its controls go with it. */
  focusAfterDelete: RefObject<HTMLElement | null>;
}

/**
 * One ruled line of the documents list: the file, its facts and where its processing stands.
 * The name is the link, stretched over the whole line; the buttons sit above it.
 */
export function DocumentRow({ document, focusAfterDelete }: DocumentRowProps) {
  const t = useTranslations("Documents.row");
  const locale = useLocale();
  const linkRef = useRef<HTMLAnchorElement>(null);
  const progress = documentProgress(document);
  const name = document.title ?? document.original_filename;
  const FileIcon = FILE_ICONS[document.content_type];

  return (
    <li className="hover:bg-paper relative flex gap-3 px-5 py-4 transition-colors sm:gap-4 sm:px-6">
      <FileIcon aria-hidden className="text-ink-soft mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 flex-1">
        {/* Room for the delete button is kept beside the name only, so the lines under it
            keep the whole width on a phone. */}
        <div className="flex flex-col gap-x-6 gap-y-2 sm:flex-row sm:items-start sm:justify-between sm:pr-10">
          <div className="min-w-0 pr-10 sm:pr-0">
            <Link
              ref={linkRef}
              href={`/documents/${document.id}`}
              title={name}
              className="text-ink focus-visible:after:outline-pen block truncate font-medium after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-solid"
            >
              {name}
            </Link>
            <p className="text-ink-soft mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <span>{formatBytes(document.size_bytes, locale)}</span>
              {document.page_count === null ? null : (
                <span>{t("pages", { count: document.page_count })}</span>
              )}
              {document.word_count === null ? null : (
                <span>{t("words", { count: document.word_count })}</span>
              )}
            </p>
          </div>
          <StageLine
            status={document.status}
            progress={progress}
            className="sm:w-60 sm:shrink-0 sm:pt-0.5"
          />
        </div>
        <ProgressNote
          document={document}
          progress={progress}
          onRetried={() => linkRef.current?.focus()}
        />
      </div>
      <DeleteDocumentButton document={document} focusAfterDelete={focusAfterDelete} />
    </li>
  );
}

interface StageLineProps {
  status: DocumentOut["status"];
  progress: DocumentProgress;
  className?: string;
}

/** The stage in words, next to the rail; a ready document rests with a single dot. */
export function StageLine({ status, progress, className }: StageLineProps) {
  const t = useTranslations("Documents.stage");

  if (progress.kind === "ready") {
    return (
      <p className={cn("text-ink flex items-center gap-2 text-sm", className)}>
        <span aria-hidden className="bg-ok size-2 shrink-0 rounded-full" />
        {t("ready")}
      </p>
    );
  }
  let label: string;
  if (progress.kind === "failed") {
    label = t("failed");
  } else if (progress.note === "retryPending") {
    label = t("retryPending");
  } else {
    label = t(progress.stage);
  }
  return (
    // Aligned to the first line, so a label that wraps never pulls the rail out of its column.
    <p className={cn("text-ink flex items-start gap-2.5 text-sm", className)}>
      <StatusRail
        status={status}
        moving={progress.kind === "active" && progress.note === null}
        className="mt-0.5"
      />
      <span>{label}</span>
    </p>
  );
}

interface ProgressNoteProps {
  document: DocumentOut;
  progress: DocumentProgress;
  onRetried: () => void;
}

/** Why a document failed, or that it has stalled, with Retry when processing can start again. */
function ProgressNote({ document, progress, onRetried }: ProgressNoteProps) {
  const t = useTranslations("Documents.row");
  const tErrors = useTranslations("Documents.processingErrors");

  let note: ReactNode;
  if (progress.kind === "failed") {
    note = (
      <p className="text-margin text-sm">{processingErrorMessage(progress.errorCode, tErrors)}</p>
    );
  } else if (progress.kind === "active" && progress.note === "stalled") {
    note = <p className="text-ink-soft text-sm">{t("stalled")}</p>;
  } else {
    return null;
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
      {note}
      {document.can_retry ? <RetryAction document={document} onRetried={onRetried} /> : null}
    </div>
  );
}

function RetryAction({ document, onRetried }: { document: DocumentOut; onRetried: () => void }) {
  const t = useTranslations("Documents.row");
  const tErrors = useTranslations("Documents.errors");
  const retry = useRetryDocument(document);

  function retryProcessing() {
    retry.mutate(undefined, {
      // Retry goes away once the document is on its way again, so focus stays in the row.
      onSuccess: (updated) => {
        if (!updated.can_retry) {
          onRetried();
        }
      },
    });
  }

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        isLoading={retry.isPending}
        aria-label={t("retryLabel", { filename: document.original_filename })}
        className="relative"
        onClick={retryProcessing}
      >
        {t("retry")}
      </Button>
      {retry.isError ? (
        <p role="alert" className="text-margin basis-full text-sm">
          {documentErrorMessage(retry.error, "retry", tErrors)}
        </p>
      ) : null}
    </>
  );
}

function DeleteDocumentButton({ document, focusAfterDelete }: DocumentRowProps) {
  const t = useTranslations("Documents");
  const tErrors = useTranslations("Documents.errors");
  const deletion = useDeleteDocument(document);
  const filename = document.original_filename;

  return (
    <AlertDialog
      trigger={
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("row.delete", { filename })}
          // Centred on the name's line, with the icon on the row's text edge.
          className="absolute top-2 right-2 sm:right-3"
        >
          <TrashIcon aria-hidden />
        </Button>
      }
      title={t("deleteDialog.title")}
      description={t("deleteDialog.description", { filename })}
      confirmLabel={t("deleteDialog.confirm")}
      onConfirm={() => deletion.mutateAsync()}
      errorMessage={(error) => documentErrorMessage(error, "delete", tErrors)}
      focusAfterConfirm={focusAfterDelete}
    />
  );
}
