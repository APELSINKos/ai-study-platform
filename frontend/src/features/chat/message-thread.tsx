"use client";

import { useLocale, useTranslations } from "next-intl";

import { isBuiltInModel } from "@/features/meta/models";
import type { ChatMessageOut } from "@/lib/api/types";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

const PARAGRAPH_BREAK = /\n{2,}/;

interface MessageThreadProps {
  messages: readonly ChatMessageOut[];
  pendingMessages: readonly string[];
  className?: string;
}

/**
 * The chronological conversation turns of a chat session: user prompts, grounded answers in book
 * serif, honest localized callouts when context is insufficient, and any turn still in flight.
 */
export function MessageThread({ messages, pendingMessages, className }: MessageThreadProps) {
  const t = useTranslations("Chat.thread");

  if (messages.length === 0 && pendingMessages.length === 0) {
    return (
      <p className={cn("text-ink-soft max-w-[58ch] text-base leading-7", className)}>
        {t("empty")}
      </p>
    );
  }

  return (
    <ol aria-label={t("label")} className={cn("flex flex-col gap-6", className)}>
      {messages.map((message) => (
        <li key={message.id}>
          {message.role === "user" ? (
            <UserMessage content={message.content} />
          ) : (
            <AssistantMessage message={message} />
          )}
        </li>
      ))}
      {pendingMessages.map((content, index) => (
        <li key={`pending-${index}`} className="flex flex-col gap-6">
          <UserMessage content={content} />
          <PendingAssistantMessage />
        </li>
      ))}
    </ol>
  );
}

function UserMessage({ content }: { content: string }) {
  const t = useTranslations("Chat.thread");
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-ink-soft text-xs font-medium">{t("you")}</p>
      <div className="border-rule bg-paper rounded-panel max-w-[65ch] border px-4 py-3">
        <p className="text-ink text-[0.9375rem] leading-6 break-words whitespace-pre-wrap">
          {content}
        </p>
      </div>
    </div>
  );
}

function AssistantMessage({ message }: { message: ChatMessageOut }) {
  const t = useTranslations("Chat.thread");
  const locale = useLocale();
  const hasDuration = message.retrieval_ms !== null || message.generation_ms !== null;
  const totalMs = (message.retrieval_ms ?? 0) + (message.generation_ms ?? 0);
  const paragraphs = message.content
    .split(PARAGRAPH_BREAK)
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph.length > 0);

  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-pen text-xs font-medium">{t("assistant")}</p>
      {message.insufficient_context ? (
        // Never render backend `message.content` when insufficient_context is true: show localized
        // copy distinguishing skipped retrieval (`model === null`) from uncovered passages.
        <div className="border-margin/70 bg-paper/70 max-w-[65ch] border-l-2 px-4 py-3">
          <p className="font-display text-ink text-[0.9375rem] leading-7">
            {message.model === null ? t("insufficientNoPassages") : t("insufficientNotCovered")}
          </p>
        </div>
      ) : (
        <div className="font-display text-ink max-w-[65ch] space-y-3 text-base leading-7 break-words">
          {paragraphs.map((paragraph, index) => (
            <p key={index} className="whitespace-pre-line">
              {paragraph}
            </p>
          ))}
        </div>
      )}
      <p className="text-ink-soft mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {hasDuration ? <span>{formatDuration(totalMs, locale)}</span> : null}
        {!message.insufficient_context && message.citations.length > 0 ? (
          <span>{t("sourcesCount", { count: message.citations.length })}</span>
        ) : null}
        {isBuiltInModel(message.model) ? <span>{t("offlineAnswer")}</span> : null}
      </p>
    </div>
  );
}

function PendingAssistantMessage() {
  const t = useTranslations("Chat.thread");
  return (
    <div aria-busy="true" className="flex flex-col gap-1.5">
      <p className="text-pen text-xs font-medium">{t("assistant")}</p>
      <p className="text-ink-soft text-sm">{t("thinking")}</p>
    </div>
  );
}
