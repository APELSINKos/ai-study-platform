"use client";

import { PencilSimpleIcon, SlidersHorizontalIcon, TrashIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent, type RefObject } from "react";

import { AlertDialog } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { IndexCard, IndexCardBody, IndexCardHeader } from "@/components/ui/index-card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceDocuments } from "@/features/documents/hooks";
import { useMeta } from "@/features/meta/hooks";
import { ApiError } from "@/lib/api/errors";
import type { ChatSessionDetailOut } from "@/lib/api/types";
import { useFocusOnArrival } from "@/lib/use-focus-on-arrival";

import {
  DocumentScopePicker,
  reconcileScopeDocumentIds,
  type ScopeMode,
} from "./document-scope-picker";
import { CHAT_SESSION_NOT_FOUND_CODE, chatErrorMessage } from "./error-message";
import {
  useChatSession,
  useDeleteChatSession,
  usePendingChatMessages,
  useSendMessage,
  useUpdateChatSession,
} from "./hooks";
import { MessageThread } from "./message-thread";
import { SessionsDrawer } from "./sessions-drawer";

const MAX_TITLE_LENGTH = 200;
const DEFAULT_MAX_SCOPE_DOCUMENTS = 50;
const DEFAULT_MAX_MESSAGES_PER_SESSION = 200;
const MESSAGES_PER_TURN = 2;

const MISSING_SESSION_CODES: ReadonlySet<string> = new Set([
  CHAT_SESSION_NOT_FOUND_CODE,
  "validation_error",
]);

function isMissingSession(error: unknown): boolean {
  return error instanceof ApiError && MISSING_SESSION_CODES.has(error.code);
}

type HeadingRef = RefObject<HTMLHeadingElement | null>;
type ActiveEditor = "none" | "rename" | "scope";

interface ChatSessionViewProps {
  sessionId: string;
  draft: string;
  onDraftChange: (next: string) => void;
  onRestoreDraft: (sessionId: string, content: string) => void;
}

/**
 * Active chat conversation view, keyed by `sessionId` so switching sessions resets transient
 * inline editors while per-session drafts and in-flight sends survive via parent state and
 * `useMutationState`.
 */
export function ChatSessionView({
  sessionId,
  draft,
  onDraftChange,
  onRestoreDraft,
}: ChatSessionViewProps) {
  // Keep showing the session while deleting it so it does not flash Not Found mid-redirect.
  const [deleting, setDeleting] = useState<ChatSessionDetailOut | null>(null);
  const query = useChatSession(sessionId, { enabled: deleting === null });
  const headingRef = useRef<HTMLHeadingElement>(null);
  // Checked before data: a session deleted elsewhere is gone even if a cached copy exists.
  const isMissing = deleting === null && isMissingSession(query.error);
  const session = deleting ?? (isMissing ? undefined : query.data);

  const focusHeadingOnArrival = useFocusOnArrival(
    isMissing ? "missing" : session === undefined ? "absent" : "shown",
    headingRef,
  );

  if (isMissing) {
    return <ChatNotFound headingRef={headingRef} />;
  }
  if (session !== undefined) {
    return (
      <ActiveSessionPage
        session={session}
        headingRef={headingRef}
        draft={draft}
        onDraftChange={onDraftChange}
        onRestoreDraft={onRestoreDraft}
        onDeleting={setDeleting}
      />
    );
  }
  if (query.isPending) {
    return <ChatSessionSkeleton />;
  }
  return (
    <ChatSessionLoadError
      error={query.error}
      isRetrying={query.isFetching}
      onRetry={() => {
        focusHeadingOnArrival();
        void query.refetch();
      }}
    />
  );
}

interface ActiveSessionPageProps {
  session: ChatSessionDetailOut;
  headingRef: HeadingRef;
  draft: string;
  onDraftChange: (next: string) => void;
  onRestoreDraft: (sessionId: string, content: string) => void;
  onDeleting: (session: ChatSessionDetailOut | null) => void;
}

function ActiveSessionPage({
  session,
  headingRef,
  draft,
  onDraftChange,
  onRestoreDraft,
  onDeleting,
}: ActiveSessionPageProps) {
  const t = useTranslations("Chat");
  const tErrors = useTranslations("Chat.errors");
  const router = useRouter();
  const meta = useMeta().data;

  const [activeEditor, setActiveEditor] = useState<ActiveEditor>("none");
  const [renameValue, setRenameValue] = useState("");
  const [scopeMode, setScopeMode] = useState<ScopeMode>("all");
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const returnFocusToRef = useRef<"rename" | "scope" | null>(null);

  const updateSession = useUpdateChatSession(session.id);
  const deleteSession = useDeleteChatSession(session.id);
  const sendMessage = useSendMessage(session.id, { onRestoreDraft });
  const pendingMessages = usePendingChatMessages(session.id);

  const title = session.title ?? t("untitled");
  const maxScopeDocuments = meta?.chat.max_scope_documents ?? DEFAULT_MAX_SCOPE_DOCUMENTS;
  const maxMessages = meta?.chat.max_messages_per_session ?? DEFAULT_MAX_MESSAGES_PER_SESSION;
  const isAtLimit = session.message_count + MESSAGES_PER_TURN > maxMessages;
  const isSending = sendMessage.isPending || pendingMessages.length > 0;

  function openRename() {
    setRenameValue(session.title ?? "");
    updateSession.reset();
    setActiveEditor("rename");
  }

  function openScope() {
    setScopeMode(session.document_ids === null ? "all" : "selected");
    setSelectedDocIds(session.document_ids ?? []);
    updateSession.reset();
    setActiveEditor("scope");
  }

  function closeEditor(trigger: "rename" | "scope") {
    returnFocusToRef.current = trigger;
    setActiveEditor("none");
  }

  function takeRenameFocus(button: HTMLButtonElement | null) {
    if (button && returnFocusToRef.current === "rename") {
      returnFocusToRef.current = null;
      button.focus();
    }
  }

  function takeScopeFocus(button: HTMLButtonElement | null) {
    if (button && returnFocusToRef.current === "scope") {
      returnFocusToRef.current = null;
      button.focus();
    }
  }

  function handleSaveRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (updateSession.isPending) {
      return;
    }
    const trimmed = renameValue.trim();
    updateSession.mutate(
      { title: trimmed === "" ? null : trimmed },
      { onSuccess: () => closeEditor("rename") },
    );
  }

  function handleDelete() {
    onDeleting(session);
    return deleteSession.mutateAsync(undefined, {
      onSuccess: () => router.replace("/chat"),
      onError: () => onDeleting(null),
    });
  }

  function submitDraft() {
    if (isSending || isAtLimit) {
      return;
    }
    const cleaned = draft.trim().toWellFormed();
    if (cleaned === "") {
      return;
    }
    setAnnouncement("");
    sendMessage.reset();
    onDraftChange("");
    sendMessage.mutate(
      { sessionId: session.id, content: cleaned },
      {
        onSuccess: (turn) => {
          const reply = turn.assistant_message;
          setAnnouncement(
            reply.insufficient_context
              ? t("status.insufficientReply")
              : t("status.replyArrived", { count: reply.citations.length }),
          );
        },
      },
    );
  }

  function handleComposerSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitDraft();
  }

  function handleTextareaKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.nativeEvent.isComposing &&
      !event.shiftKey &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey
    ) {
      event.preventDefault();
      submitDraft();
    }
  }

  return (
    <div className="notebook-row">
      <div className="margin-note flex flex-wrap gap-x-3 gap-y-1 md:flex-col md:items-end">
        <Link
          href={`/workspaces/${session.workspace_id}`}
          aria-label={`${t("session.workspaceLabel")}: ${session.workspace_name}`}
          className="decoration-pen/50 hover:decoration-pen line-clamp-3 pb-0.5 break-words underline underline-offset-4"
        >
          {session.workspace_name}
        </Link>
        <span className="text-ink-soft text-xs not-italic">
          {session.document_ids === null
            ? t("session.scopeAll")
            : t("session.scopeSelected", { count: session.document_ids.length })}
        </span>
      </div>

      <div className="max-w-3xl">
        <div className="flex flex-col gap-4">
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="font-display text-title w-fit max-w-full font-semibold break-words"
          >
            {title}
          </h1>
          <div className="flex flex-wrap items-center gap-2">
            <SessionsDrawer activeSessionId={session.id} />
            {activeEditor !== "rename" ? (
              <Button ref={takeRenameFocus} variant="ghost" size="sm" onClick={openRename}>
                <PencilSimpleIcon aria-hidden />
                {t("session.renameButton")}
              </Button>
            ) : null}
            {activeEditor !== "scope" ? (
              <Button ref={takeScopeFocus} variant="ghost" size="sm" onClick={openScope}>
                <SlidersHorizontalIcon aria-hidden />
                {t("session.scopeButton")}
              </Button>
            ) : null}
            <AlertDialog
              trigger={
                <Button variant="danger" size="sm">
                  <TrashIcon aria-hidden />
                  {t("session.deleteButton")}
                </Button>
              }
              title={t("deleteDialog.title")}
              description={t("deleteDialog.description", { title })}
              confirmLabel={t("deleteDialog.confirm")}
              onConfirm={handleDelete}
              errorMessage={(error) => chatErrorMessage(error, "deleteSession", tErrors)}
            />
          </div>
        </div>

        {activeEditor === "rename" ? (
          <RenameSessionForm
            value={renameValue}
            onChange={setRenameValue}
            isSaving={updateSession.isPending}
            error={
              updateSession.error
                ? chatErrorMessage(updateSession.error, "updateSession", tErrors)
                : null
            }
            onSubmit={handleSaveRename}
            onCancel={() => closeEditor("rename")}
            className="mt-5"
          />
        ) : null}

        {activeEditor === "scope" ? (
          <SessionScopeEditor
            workspaceId={session.workspace_id}
            scopeMode={scopeMode}
            onScopeModeChange={setScopeMode}
            selectedDocIds={selectedDocIds}
            onSelectedDocIdsChange={setSelectedDocIds}
            maxScopeDocuments={maxScopeDocuments}
            isSaving={updateSession.isPending}
            error={
              updateSession.error
                ? chatErrorMessage(updateSession.error, "updateSession", tErrors)
                : null
            }
            onSave={(nextDocumentIds) =>
              updateSession.mutate(
                { document_ids: nextDocumentIds },
                { onSuccess: () => closeEditor("scope") },
              )
            }
            onCancel={() => closeEditor("scope")}
            className="mt-5"
          />
        ) : null}

        <MessageThread
          messages={session.messages}
          pendingMessages={pendingMessages}
          className="mt-8"
        />

        <div role="status" className="sr-only">
          {announcement}
        </div>

        {isAtLimit ? (
          <div className="border-rule-strong mt-8 flex flex-col items-start gap-3 border-l-2 pl-4">
            <p className="text-ink-soft text-sm">
              {t("composer.limitReached", { max: maxMessages })}
            </p>
            <Button asChild variant="primary" size="sm">
              <Link href={`/chat?workspace=${session.workspace_id}`}>
                {t("composer.startNewChat")}
              </Link>
            </Button>
          </div>
        ) : (
          <form onSubmit={handleComposerSubmit} className="border-rule mt-8 border-t pt-5">
            <Field label={t("composer.label")} hint={t("composer.hint")}>
              <Textarea
                value={draft}
                onChange={(event) => {
                  if (sendMessage.error) {
                    sendMessage.reset();
                  }
                  onDraftChange(event.target.value);
                }}
                onKeyDown={handleTextareaKeyDown}
                placeholder={t("composer.placeholder")}
                maxLength={meta?.chat.max_message_chars}
                aria-busy={isSending || undefined}
                rows={3}
              />
            </Field>
            {sendMessage.error ? (
              <p role="alert" className="text-margin mt-3 text-sm">
                {chatErrorMessage(sendMessage.error, "sendMessage", tErrors)}
              </p>
            ) : null}
            <div className="mt-4 flex items-center justify-end">
              <Button type="submit" variant="primary" isLoading={isSending}>
                {t("composer.send")}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

interface RenameSessionFormProps {
  value: string;
  onChange: (next: string) => void;
  isSaving: boolean;
  error: string | null;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
  className?: string;
}

function RenameSessionForm({
  value,
  onChange,
  isSaving,
  error,
  onSubmit,
  onCancel,
  className,
}: RenameSessionFormProps) {
  const t = useTranslations("Chat.session.rename");
  const headingId = useId();
  return (
    <IndexCard className={className}>
      <IndexCardHeader>
        <h2 id={headingId} className="font-display text-lg font-semibold">
          {t("title")}
        </h2>
      </IndexCardHeader>
      <IndexCardBody
        as="form"
        aria-labelledby={headingId}
        onSubmit={onSubmit}
        className="flex flex-col gap-4"
      >
        <Field label={t("label")} hint={t("hint")}>
          <Input
            value={value}
            onChange={(event) => onChange(event.target.value)}
            maxLength={MAX_TITLE_LENGTH}
            autoFocus
          />
        </Field>
        {error ? (
          <p role="alert" className="text-margin text-sm">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="secondary" size="sm" isLoading={isSaving}>
            {t("save")}
          </Button>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
        </div>
      </IndexCardBody>
    </IndexCard>
  );
}

interface SessionScopeEditorProps {
  workspaceId: string;
  scopeMode: ScopeMode;
  onScopeModeChange: (mode: ScopeMode) => void;
  selectedDocIds: readonly string[];
  onSelectedDocIdsChange: (nextIds: string[]) => void;
  maxScopeDocuments: number;
  isSaving: boolean;
  error: string | null;
  onSave: (documentIds: string[] | null) => void;
  onCancel: () => void;
  className?: string;
}

function SessionScopeEditor({
  workspaceId,
  scopeMode,
  onScopeModeChange,
  selectedDocIds,
  onSelectedDocIdsChange,
  maxScopeDocuments,
  isSaving,
  error,
  onSave,
  onCancel,
  className,
}: SessionScopeEditorProps) {
  const t = useTranslations("Chat.session.scope");
  const headingId = useId();
  const documents = useWorkspaceDocuments(workspaceId);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSaving || (scopeMode === "selected" && documents.isPending)) {
      return;
    }
    const nextDocumentIds =
      scopeMode === "all"
        ? null
        : reconcileScopeDocumentIds(
            selectedDocIds,
            documents.data?.documents ?? [],
            documents.hasNextPage,
          );
    onSave(nextDocumentIds);
  }

  return (
    <IndexCard className={className}>
      <IndexCardHeader>
        <h2 id={headingId} className="font-display text-lg font-semibold">
          {t("title")}
        </h2>
      </IndexCardHeader>
      <IndexCardBody
        as="form"
        aria-labelledby={headingId}
        onSubmit={handleSubmit}
        className="flex flex-col gap-4"
      >
        <DocumentScopePicker
          workspaceId={workspaceId}
          scopeMode={scopeMode}
          onScopeModeChange={onScopeModeChange}
          selectedIds={selectedDocIds}
          onSelectedIdsChange={onSelectedDocIdsChange}
          maxScopeDocuments={maxScopeDocuments}
        />
        {error ? (
          <p role="alert" className="text-margin text-sm">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="submit"
            variant="secondary"
            size="sm"
            isLoading={isSaving || (scopeMode === "selected" && documents.isPending)}
          >
            {t("save")}
          </Button>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
        </div>
      </IndexCardBody>
    </IndexCard>
  );
}

/** Shown for a missing, deleted or malformed `?session=` address. */
export function ChatNotFound({ headingRef }: { headingRef?: HeadingRef }) {
  const t = useTranslations("Chat.session.notFound");
  return (
    <div className="notebook-row">
      <div className="max-w-3xl">
        <h1 ref={headingRef} tabIndex={-1} className="font-display text-title w-fit font-semibold">
          {t("title")}
        </h1>
        <p className="text-ink-soft mt-4 max-w-[58ch] text-lg leading-8">{t("lead")}</p>
        <Button asChild variant="primary" className="mt-8">
          <Link href="/chat">{t("back")}</Link>
        </Button>
      </div>
    </div>
  );
}

function ChatSessionSkeleton() {
  const t = useTranslations("Chat");
  return (
    <div className="notebook-row">
      <div aria-busy="true" className="max-w-3xl">
        <h1 className="sr-only">{t("metaTitle")}</h1>
        <p className="sr-only">{t("session.loading")}</p>
        <div aria-hidden>
          <div className="bg-ink/10 h-10 w-72 max-w-full rounded motion-safe:animate-pulse" />
          <div className="bg-ink/10 mt-6 h-16 w-full max-w-xl rounded motion-safe:animate-pulse" />
          <div className="bg-ink/10 mt-4 h-24 w-full max-w-2xl rounded motion-safe:animate-pulse" />
        </div>
      </div>
    </div>
  );
}

function ChatSessionLoadError({
  error,
  isRetrying,
  onRetry,
}: {
  error: unknown;
  isRetrying: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations("Chat");
  const tErrors = useTranslations("Chat.errors");
  return (
    <div className="notebook-row">
      <div className="flex max-w-3xl flex-col items-start gap-4">
        <h1 className="sr-only">{t("metaTitle")}</h1>
        <p role="alert" className="text-ink-soft">
          {chatErrorMessage(error, "openSession", tErrors)}
        </p>
        <Button variant="secondary" isLoading={isRetrying} onClick={onRetry}>
          {t("session.retry")}
        </Button>
      </div>
    </div>
  );
}
