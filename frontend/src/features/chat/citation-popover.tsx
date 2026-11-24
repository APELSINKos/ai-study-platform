"use client";

import { ArrowSquareOutIcon, XIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Popover } from "radix-ui";

import { CitationMark } from "@/components/citation-mark";
import { Button } from "@/components/ui/button";
import { passageHref } from "@/features/documents/passage-href";
import { headingBelowTitle, pageRange } from "@/features/documents/passage-meta";
import type { CitationOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

interface CitationPopoverProps {
  citation: CitationOut;
  /** `inline` renders the compact numbered badge inside prose; `source` shows title beside badge. */
  variant?: "inline" | "source";
  className?: string;
}

/**
 * Interactive citation trigger and portal popover showing the immutable passage quote snapshot
 * and a deep link to that exact passage inside its source document.
 */
export function CitationPopover({ citation, variant = "inline", className }: CitationPopoverProps) {
  const t = useTranslations("Chat.citation");
  const citationLabel = t("citationLabel", {
    index: citation.index,
    title: citation.document_title,
  });
  const heading = headingBelowTitle(citation);
  const pages = pageRange(citation, {
    page: (page) => t("page", { page }),
    pages: (start, end) => t("pages", { start, end }),
  });

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        {variant === "inline" ? (
          <button
            type="button"
            aria-label={citationLabel}
            className={cn(
              "focus-visible:outline-pen inline-flex size-6 cursor-pointer items-center justify-center rounded-full align-middle focus-visible:outline-2 focus-visible:outline-offset-2 motion-safe:transition-transform motion-safe:hover:scale-105",
              className,
            )}
          >
            <CitationMark number={citation.index} aria-hidden />
          </button>
        ) : (
          <button
            type="button"
            aria-label={citationLabel}
            className={cn(
              "border-rule-strong bg-sheet text-ink hover:bg-paper focus-visible:outline-pen rounded-control inline-flex max-w-full cursor-pointer items-center gap-2 border px-2.5 py-1 text-left text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2",
              className,
            )}
          >
            <CitationMark number={citation.index} aria-hidden className="shrink-0" />
            <span className="truncate">{citation.document_title}</span>
          </button>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          aria-label={citationLabel}
          sideOffset={8}
          collisionPadding={16}
          className="index-card z-30 w-[min(22rem,calc(100vw-2rem))] overflow-hidden p-0 focus:outline-none"
        >
          <div className="index-card-header flex items-start justify-between gap-2 px-4 py-3">
            <div className="flex min-w-0 items-start gap-2.5">
              <CitationMark number={citation.index} aria-hidden className="mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-ink text-sm font-semibold break-words">
                  {citation.document_title}
                </p>
                {heading !== null || pages !== null ? (
                  <p className="text-ink-soft mt-0.5 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {heading !== null ? (
                      <span className="min-w-0 break-words">{heading}</span>
                    ) : null}
                    {pages !== null ? <span>{pages}</span> : null}
                  </p>
                ) : null}
              </div>
            </div>
            <Popover.Close asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("closePreview")}
                className="-mt-1 -mr-2 size-8 shrink-0"
              >
                <XIcon aria-hidden className="size-4" />
              </Button>
            </Popover.Close>
          </div>
          <div className="px-4 py-3">
            <blockquote className="font-display text-ink text-sm leading-6 break-words">
              {citation.quote}
            </blockquote>
            <div className="mt-3">
              <Link
                href={passageHref(citation.document_id, citation.chunk_index)}
                className="text-pen focus-visible:outline-pen inline-flex items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                {t("openPassage")}
                <ArrowSquareOutIcon aria-hidden className="size-4" />
              </Link>
            </div>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
