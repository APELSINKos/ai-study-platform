"use client";

import {
  CircleNotchIcon,
  FileIcon,
  FileMdIcon,
  FilePdfIcon,
  FileTxtIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

import { documentErrorMessage, waitOf } from "./error-message";
import { extensionOf, listExtensions, type FileRules } from "./file-rules";
import type { UploadItem, UploadState } from "./use-upload-queue";

type ResultsTranslator = ReturnType<typeof useTranslations<"Documents.upload.results">>;
type UploadKind = UploadState["kind"];

const FILE_ICONS: Readonly<Record<string, Icon>> = {
  ".pdf": FilePdfIcon,
  ".md": FileMdIcon,
  ".txt": FileTxtIcon,
};

type UploadSummary =
  | { kind: "uploading"; position: number; total: number }
  | { kind: "done"; uploaded: number; notUploaded: number };

function summarize(items: readonly UploadItem[]): UploadSummary | null {
  if (items.length === 0) {
    return null;
  }
  const counts: Record<UploadKind, number> = {
    rejected: 0,
    waiting: 0,
    uploading: 0,
    uploaded: 0,
    failed: 0,
    notSent: 0,
  };
  for (const item of items) {
    counts[item.state.kind] += 1;
  }
  const sent = counts.uploaded + counts.failed;
  const left = counts.uploading + counts.waiting;
  if (left > 0) {
    // Files turned down before sending are not part of the run.
    return { kind: "uploading", position: sent + 1, total: sent + left };
  }
  return {
    kind: "done",
    uploaded: counts.uploaded,
    notUploaded: counts.rejected + counts.failed + counts.notSent,
  };
}

function summaryText(summary: UploadSummary, t: ResultsTranslator): string {
  if (summary.kind === "uploading") {
    return t("summary.uploading", { position: summary.position, total: summary.total });
  }
  const sentences: string[] = [];
  if (summary.uploaded > 0) {
    sentences.push(t("summary.uploaded", { count: summary.uploaded }));
  }
  if (summary.notUploaded > 0) {
    sentences.push(t("summary.notUploaded", { count: summary.notUploaded }));
  }
  return sentences.join(" ");
}

interface UploadResultsProps {
  items: readonly UploadItem[];
  /** Empties the list; offered once no file is left to upload. */
  onClear: () => void;
  className?: string;
}

/**
 * The files added for upload as ruled rows, each with what became of it, under one polite live
 * region that sums them up. The region stays in place while empty, so that its first message is
 * announced as well.
 */
export function UploadResults({ items, onClear, className }: UploadResultsProps) {
  const t = useTranslations("Documents.upload.results");
  const summary = summarize(items);

  return (
    <div className={cn(summary && "mt-5", className)}>
      <div className={cn("flex items-center justify-between gap-x-4", summary && "min-h-8")}>
        <p role="status" className="text-ink-soft text-sm">
          {summary ? summaryText(summary, t) : null}
        </p>
        {summary?.kind === "done" ? (
          // Its text lines up with the right edge of the rows below.
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("clearLabel")}
            className="-mr-3"
            onClick={onClear}
          >
            {t("clear")}
          </Button>
        ) : null}
      </div>
      {items.length > 0 ? (
        <ul aria-label={t("label")} className="border-rule divide-rule mt-1 divide-y border-y">
          {items.map((item) => (
            <UploadRow key={item.id} item={item} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function UploadRow({ item }: { item: UploadItem }) {
  const locale = useLocale();
  const TypeIcon = FILE_ICONS[extensionOf(item.name)] ?? FileIcon;

  return (
    <li className="flex gap-3 py-3 sm:gap-4">
      <TypeIcon aria-hidden className="text-ink-soft mt-0.5 size-5 shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col gap-x-6 gap-y-1 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p title={item.name} className="text-ink truncate font-medium">
            {item.name}
          </p>
          <p className="text-ink-soft mt-0.5 text-sm">{formatBytes(item.size, locale)}</p>
        </div>
        <Outcome state={item.state} className="sm:w-64 sm:shrink-0 sm:pt-0.5" />
      </div>
    </li>
  );
}

function Dot({ className }: { className: string }) {
  return <span aria-hidden className={cn("mt-1.5 size-2 shrink-0 rounded-full", className)} />;
}

/** Where a file stands, in words; the mark beside them only repeats it. */
function Outcome({ state, className }: { state: UploadState; className?: string }) {
  const t = useTranslations("Documents.upload.results");
  const tErrors = useTranslations("Documents.errors");
  const locale = useLocale();

  let marker: ReactNode;
  let tone: string;
  let text: string;
  switch (state.kind) {
    case "waiting":
      marker = <Dot className="border-rule-strong border" />;
      tone = "text-ink-soft";
      text = t("state.waiting");
      break;
    case "uploading":
      marker = (
        <CircleNotchIcon
          aria-hidden
          className="text-pen mt-0.75 size-3.5 shrink-0 motion-safe:animate-spin"
        />
      );
      tone = "text-ink";
      text = t("state.uploading");
      break;
    case "uploaded":
      marker = <Dot className="bg-ok" />;
      tone = "text-ink";
      text = t("state.uploaded");
      break;
    case "rejected":
      marker = <Dot className="bg-margin" />;
      tone = "text-margin";
      text = rejectionMessage(state.reason, state.rules, t, locale);
      break;
    case "failed":
      marker = <Dot className="bg-margin" />;
      tone = "text-margin";
      text = documentErrorMessage(state.error, "upload", tErrors);
      break;
    case "notSent":
      marker = <Dot className="border-margin border" />;
      tone = "text-ink-soft";
      text = notSentMessage(state.retryAfterSeconds, t);
      break;
  }

  return (
    <p data-outcome={state.kind} className={cn("flex items-start gap-2 text-sm", tone, className)}>
      {marker}
      <span>{text}</span>
    </p>
  );
}

function rejectionMessage(
  reason: Extract<UploadState, { kind: "rejected" }>["reason"],
  rules: FileRules,
  t: ResultsTranslator,
  locale: string,
): string {
  switch (reason) {
    case "type":
      return t("rejected.type", { types: listExtensions(rules, locale) });
    case "tooLarge":
      return t("rejected.tooLarge", { size: formatBytes(rules.max_upload_bytes, locale) });
    case "empty":
      return t("rejected.empty");
  }
}

function notSentMessage(retryAfterSeconds: number | null, t: ResultsTranslator): string {
  const wait = waitOf(retryAfterSeconds);
  if (wait === null) {
    return t("notSent.generic");
  }
  return "minutes" in wait ? t("notSent.minutes", wait) : t("notSent.seconds", wait);
}
