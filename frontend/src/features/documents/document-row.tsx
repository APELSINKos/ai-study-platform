"use client";

import { FileMdIcon, FilePdfIcon, FileTxtIcon, type Icon } from "@phosphor-icons/react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import type { DocumentContentType, DocumentOut } from "@/lib/api/types";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

import { processingErrorMessage } from "./error-message";
import { documentProgress, type DocumentProgress } from "./status";
import { StatusRail } from "./status-rail";

const FILE_ICONS = {
  "application/pdf": FilePdfIcon,
  "text/markdown": FileMdIcon,
  "text/plain": FileTxtIcon,
} as const satisfies Record<DocumentContentType, Icon>;

/**
 * One ruled line of the documents list: the file, its facts and where its processing stands.
 * The name is the link, stretched over the whole line.
 */
export function DocumentRow({ document }: { document: DocumentOut }) {
  const t = useTranslations("Documents.row");
  const locale = useLocale();
  const progress = documentProgress(document);
  const name = document.title ?? document.original_filename;
  const FileIcon = FILE_ICONS[document.content_type];

  return (
    <li className="hover:bg-paper relative flex gap-3 px-5 py-4 transition-colors sm:gap-4 sm:px-6">
      <FileIcon aria-hidden className="text-ink-soft mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-col gap-x-6 gap-y-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <Link
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
        <ProgressNote progress={progress} />
      </div>
    </li>
  );
}

interface StageLineProps {
  status: DocumentOut["status"];
  progress: DocumentProgress;
  className?: string;
}

/** The stage in words, next to the rail; a ready document rests with a single dot. */
function StageLine({ status, progress, className }: StageLineProps) {
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

/** Why a document failed, or that it has stalled. */
function ProgressNote({ progress }: { progress: DocumentProgress }) {
  const t = useTranslations("Documents.row");
  const tErrors = useTranslations("Documents.processingErrors");

  if (progress.kind === "failed") {
    return (
      <p className="text-margin mt-2 text-sm">
        {processingErrorMessage(progress.errorCode, tErrors)}
      </p>
    );
  }
  if (progress.kind === "active" && progress.note === "stalled") {
    return <p className="text-ink-soft mt-2 text-sm">{t("stalled")}</p>;
  }
  return null;
}
