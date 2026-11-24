"use client";

import { TrashIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, type RefObject } from "react";

import { AlertDialog } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { IndexCard } from "@/components/ui/index-card";
import type { ChatSessionOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { chatErrorMessage } from "./error-message";
import { useChatSessions, useDeleteChatSession } from "./hooks";

const SKELETON_ROWS = 3;

function formatSessionDate(iso: string, locale: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return iso;
  }
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(parsed);
}

interface SessionListProps {
  workspaceId: string | null;
  activeSessionId?: string | null;
  focusAfterDelete: RefObject<HTMLElement | null>;
  onSelectSession?: () => void;
  onDeletingSession?: (sessionId: string) => void;
  onDeleteSessionError?: (sessionId: string) => void;
  onDeletedSession?: (sessionId: string) => void;
  isFiltered?: boolean;
  variant?: "card" | "drawer";
  hideWhenEmpty?: boolean;
  className?: string;
}

/**
 * Infinite list of chat sessions, rendered as a ruled index card on `/chat` or as a compact list
 * inside the active session's slide-over drawer.
 */
export function SessionList({
  workspaceId,
  activeSessionId = null,
  focusAfterDelete,
  onSelectSession,
  onDeletingSession,
  onDeleteSessionError,
  onDeletedSession,
  isFiltered = false,
  variant = "card",
  hideWhenEmpty = false,
  className,
}: SessionListProps) {
  const t = useTranslations("Chat.list");
  const tErrors = useTranslations("Chat.errors");
  const sessions = useChatSessions(workspaceId);

  if (sessions.isPending) {
    return <SessionListSkeleton variant={variant} className={className} />;
  }
  if (sessions.data === undefined) {
    return (
      <div className={cn("flex flex-col items-start gap-4", className)}>
        <p role="alert" className="text-ink-soft text-sm">
          {chatErrorMessage(sessions.error, "loadSessions", tErrors)}
        </p>
        <Button
          variant="secondary"
          size="sm"
          isLoading={sessions.isFetching}
          onClick={() => void sessions.refetch()}
        >
          {t("retry")}
        </Button>
      </div>
    );
  }
  if (sessions.data.length === 0) {
    if (hideWhenEmpty && !isFiltered) {
      return null;
    }
    return (
      <p className={cn("text-ink-soft text-sm", className)}>
        {isFiltered ? t("emptyFiltered") : t("empty")}
      </p>
    );
  }

  return (
    <SessionRows
      sessions={sessions.data}
      activeSessionId={activeSessionId}
      focusAfterDelete={focusAfterDelete}
      onSelectSession={onSelectSession}
      onDeletingSession={onDeletingSession}
      onDeleteSessionError={onDeleteSessionError}
      onDeletedSession={onDeletedSession}
      hasMore={sessions.hasNextPage}
      isLoadingMore={sessions.isFetchingNextPage}
      loadMoreError={
        sessions.isFetchNextPageError
          ? chatErrorMessage(sessions.error, "loadMoreSessions", tErrors)
          : null
      }
      onLoadMore={() => void sessions.fetchNextPage()}
      variant={variant}
      className={className}
    />
  );
}

interface SessionRowsProps {
  sessions: ChatSessionOut[];
  activeSessionId: string | null;
  focusAfterDelete: RefObject<HTMLElement | null>;
  onSelectSession?: () => void;
  onDeletingSession?: (sessionId: string) => void;
  onDeleteSessionError?: (sessionId: string) => void;
  onDeletedSession?: (sessionId: string) => void;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMoreError: string | null;
  onLoadMore: () => void;
  variant: "card" | "drawer";
  className?: string;
}

function SessionRows({
  sessions,
  activeSessionId,
  focusAfterDelete,
  onSelectSession,
  onDeletingSession,
  onDeleteSessionError,
  onDeletedSession,
  hasMore,
  isLoadingMore,
  loadMoreError,
  onLoadMore,
  variant,
  className,
}: SessionRowsProps) {
  const t = useTranslations("Chat.list");
  const listRef = useRef<HTMLUListElement>(null);
  const firstNewRowRef = useRef<number | null>(null);

  useEffect(() => {
    const index = firstNewRowRef.current;
    if (index === null || sessions.length <= index) {
      return;
    }
    firstNewRowRef.current = null;
    listRef.current?.children[index]?.querySelector("a")?.focus();
  }, [sessions.length]);

  function showMore() {
    if (isLoadingMore) {
      return;
    }
    firstNewRowRef.current = sessions.length;
    onLoadMore();
  }

  const content = (
    <>
      <ul ref={listRef} aria-label={t("label")} className="divide-rule divide-y">
        {sessions.map((session) => (
          <SessionRow
            key={session.id}
            session={session}
            isActive={activeSessionId === session.id}
            focusAfterDelete={focusAfterDelete}
            onSelectSession={onSelectSession}
            onDeletingSession={onDeletingSession}
            onDeleteSessionError={onDeleteSessionError}
            onDeletedSession={onDeletedSession}
            compact={variant === "drawer"}
          />
        ))}
      </ul>
      {hasMore ? (
        <div
          className={cn(
            "border-rule flex flex-wrap items-center gap-x-4 gap-y-2 border-t",
            variant === "drawer" ? "pt-3" : "px-5 py-3 sm:px-6",
          )}
        >
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
    </>
  );

  if (variant === "drawer") {
    return <div className={className}>{content}</div>;
  }
  return <IndexCard className={cn("overflow-hidden", className)}>{content}</IndexCard>;
}

interface SessionRowProps {
  session: ChatSessionOut;
  isActive: boolean;
  focusAfterDelete: RefObject<HTMLElement | null>;
  onSelectSession?: () => void;
  onDeletingSession?: (sessionId: string) => void;
  onDeleteSessionError?: (sessionId: string) => void;
  onDeletedSession?: (sessionId: string) => void;
  compact: boolean;
}

function SessionRow({
  session,
  isActive,
  focusAfterDelete,
  onSelectSession,
  onDeletingSession,
  onDeleteSessionError,
  onDeletedSession,
  compact,
}: SessionRowProps) {
  const t = useTranslations("Chat");
  const tErrors = useTranslations("Chat.errors");
  const locale = useLocale();
  const deletion = useDeleteChatSession(session.id);
  const title = session.title ?? t("untitled");

  async function confirmDelete() {
    onDeletingSession?.(session.id);
    try {
      await deletion.mutateAsync();
    } catch (error) {
      onDeleteSessionError?.(session.id);
      throw error;
    }
    onDeletedSession?.(session.id);
  }

  return (
    <li
      className={cn(
        "hover:bg-paper relative transition-colors",
        isActive && "bg-paper",
        compact ? "py-3 pr-10 pl-2" : "px-5 py-4 pr-14 sm:px-6 sm:pr-16",
      )}
    >
      <div className="min-w-0">
        <Link
          href={`/chat?session=${session.id}`}
          aria-current={isActive ? "page" : undefined}
          onClick={onSelectSession}
          className={cn(
            "text-ink focus-visible:after:outline-pen block break-words after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-solid",
            compact ? "text-sm font-medium" : "font-display text-lg font-semibold",
          )}
        >
          {title}
        </Link>
        <p className="text-ink-soft mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs sm:text-sm">
          <span className="min-w-0 break-words">{session.workspace_name}</span>
          <span>{t("list.messages", { count: session.message_count })}</span>
          {session.document_ids !== null ? (
            <span>{t("list.scopeCount", { count: session.document_ids.length })}</span>
          ) : null}
          <time dateTime={session.updated_at}>{formatSessionDate(session.updated_at, locale)}</time>
        </p>
      </div>
      <AlertDialog
        trigger={
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("list.deleteLabel", { title })}
            className={cn(
              "absolute top-2 right-1",
              compact ? "size-8" : "top-2.5 right-2 sm:right-3",
            )}
          >
            <TrashIcon aria-hidden />
          </Button>
        }
        title={t("deleteDialog.title")}
        description={t("deleteDialog.description", { title })}
        confirmLabel={t("deleteDialog.confirm")}
        onConfirm={confirmDelete}
        errorMessage={(error) => chatErrorMessage(error, "deleteSession", tErrors)}
        focusAfterConfirm={focusAfterDelete}
      />
    </li>
  );
}

function SessionListSkeleton({
  variant,
  className,
}: {
  variant: "card" | "drawer";
  className?: string;
}) {
  const t = useTranslations("Chat.list");
  const rows = (
    <div aria-hidden className="divide-rule divide-y">
      {Array.from({ length: SKELETON_ROWS }, (_, index) => (
        <div key={index} className={variant === "drawer" ? "py-3" : "px-5 py-4 sm:px-6"}>
          <div className="bg-ink/10 h-5 w-1/2 rounded motion-safe:animate-pulse" />
          <div className="bg-ink/10 mt-2.5 h-4 w-2/3 rounded motion-safe:animate-pulse" />
        </div>
      ))}
    </div>
  );

  if (variant === "drawer") {
    return (
      <div aria-busy="true" className={className}>
        <span className="sr-only">{t("loading")}</span>
        {rows}
      </div>
    );
  }
  return (
    <IndexCard aria-busy="true" className={className}>
      <span className="sr-only">{t("loading")}</span>
      {rows}
    </IndexCard>
  );
}
