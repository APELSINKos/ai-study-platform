"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { IndexCard } from "@/components/ui/index-card";
import { workspaceErrorMessage } from "@/features/workspaces/error-message";
import { useWorkspace, useWorkspaceList } from "@/features/workspaces/hooks";
import { useFocusOnArrival } from "@/lib/use-focus-on-arrival";

import { ChatNotFound, ChatSessionView } from "./chat-session-view";
import { useChatSessions } from "./hooks";
import { NewChatForm } from "./new-chat-form";
import { SessionList } from "./session-list";
import type { SessionParam } from "./url-params";

interface ChatViewProps {
  sessionParam: SessionParam;
  initialWorkspaceId: string | null;
}

/**
 * The `/chat` entry point. Keeps per-session drafts and send errors across session switches and
 * renders either the session index, the not-found view for malformed session URLs, or one active
 * session.
 */
export function ChatView({ sessionParam, initialWorkspaceId }: ChatViewProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [sendErrors, setSendErrors] = useState<Record<string, Error | null>>({});

  const updateDraft = useCallback((sessionId: string, value: string) => {
    setDrafts((prev) => ({ ...prev, [sessionId]: value }));
    setSendErrors((prev) => (prev[sessionId] ? { ...prev, [sessionId]: null } : prev));
  }, []);

  const restoreDraft = useCallback((sessionId: string, value: string) => {
    setDrafts((prev) => (prev[sessionId] ? prev : { ...prev, [sessionId]: value }));
  }, []);

  const recordSendError = useCallback((sessionId: string, error: Error) => {
    setSendErrors((prev) => ({ ...prev, [sessionId]: error }));
  }, []);

  const clearSendError = useCallback((sessionId: string) => {
    setSendErrors((prev) => (prev[sessionId] ? { ...prev, [sessionId]: null } : prev));
  }, []);

  if (sessionParam.kind === "invalid") {
    return <ChatNotFound />;
  }
  if (sessionParam.kind === "valid") {
    return (
      <ChatSessionView
        key={sessionParam.id}
        sessionId={sessionParam.id}
        draft={drafts[sessionParam.id] ?? ""}
        sendError={sendErrors[sessionParam.id] ?? null}
        onDraftChange={(value) => updateDraft(sessionParam.id, value)}
        onRestoreDraft={restoreDraft}
        onSendError={recordSendError}
        onClearSendError={clearSendError}
      />
    );
  }
  return (
    <ChatIndexView key={initialWorkspaceId ?? "all"} initialWorkspaceId={initialWorkspaceId} />
  );
}

function ChatIndexView({ initialWorkspaceId }: { initialWorkspaceId: string | null }) {
  const t = useTranslations("Chat");
  const tWorkspaceErrors = useTranslations("Workspaces.errors");
  const workspaces = useWorkspaceList();
  const [filterWorkspaceId, setFilterWorkspaceId] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(initialWorkspaceId !== null);
  const filterId = useId();
  const returnFocusRef = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const needsInitialWorkspace =
    initialWorkspaceId !== null &&
    workspaces.data !== undefined &&
    workspaces.data.length > 0 &&
    !workspaces.data.some((workspace) => workspace.id === initialWorkspaceId);
  const initialWorkspace = useWorkspace(initialWorkspaceId ?? "", {
    enabled: needsInitialWorkspace,
  });
  const availableWorkspaces =
    workspaces.data === undefined
      ? undefined
      : needsInitialWorkspace && initialWorkspace.data !== undefined
        ? [initialWorkspace.data, ...workspaces.data]
        : workspaces.data;

  const isLoadingWorkspaces =
    workspaces.isPending || (needsInitialWorkspace && initialWorkspace.isPending);
  const hasWorkspaces = availableWorkspaces !== undefined && availableWorkspaces.length > 0;
  const activeFilterWorkspaceId =
    filterWorkspaceId !== null && availableWorkspaces?.some((w) => w.id === filterWorkspaceId)
      ? filterWorkspaceId
      : null;

  const sessions = useChatSessions(activeFilterWorkspaceId, { enabled: hasWorkspaces });
  const focusHeadingOnArrival = useFocusOnArrival(
    !isLoadingWorkspaces && availableWorkspaces !== undefined,
    headingRef,
  );

  const isUnfilteredEmpty =
    hasWorkspaces && activeFilterWorkspaceId === null && sessions.data?.length === 0;
  const showForm = hasWorkspaces && (isFormOpen || isUnfilteredEmpty);

  function closeForm() {
    returnFocusRef.current = true;
    setIsFormOpen(false);
  }

  function takeReturningFocus(button: HTMLButtonElement | null) {
    if (button && returnFocusRef.current) {
      returnFocusRef.current = false;
      button.focus();
    }
  }

  function retryWorkspaces() {
    focusHeadingOnArrival();
    void workspaces.refetch();
  }

  return (
    <div className="notebook-row">
      <p className="margin-note">{t("marginNote")}</p>
      <div className="max-w-3xl">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
          <h1 ref={headingRef} tabIndex={-1} className="font-display text-title font-semibold">
            {t("title")}
          </h1>
          {hasWorkspaces &&
          !showForm &&
          !(activeFilterWorkspaceId === null && sessions.isPending) ? (
            <Button ref={takeReturningFocus} variant="primary" onClick={() => setIsFormOpen(true)}>
              {t("newChat")}
            </Button>
          ) : null}
        </div>

        {isLoadingWorkspaces ? (
          <IndexCard aria-busy="true" className="mt-8 p-6">
            <span className="sr-only">{t("list.loading")}</span>
            <div aria-hidden className="space-y-3">
              <div className="bg-ink/10 h-5 w-1/2 rounded motion-safe:animate-pulse" />
              <div className="bg-ink/10 h-4 w-2/3 rounded motion-safe:animate-pulse" />
            </div>
          </IndexCard>
        ) : availableWorkspaces === undefined ? (
          <div className="mt-8 flex flex-col items-start gap-4">
            <p role="alert" className="text-ink-soft text-sm">
              {workspaceErrorMessage(workspaces.error, "load", tWorkspaceErrors)}
            </p>
            <Button variant="secondary" isLoading={workspaces.isFetching} onClick={retryWorkspaces}>
              {t("list.retry")}
            </Button>
          </div>
        ) : availableWorkspaces.length === 0 ? (
          <div className="mt-6">
            <h2 className="font-display text-xl font-semibold">{t("emptyWorkspaces.title")}</h2>
            <p className="text-ink-soft mt-3 max-w-[58ch] text-base leading-7">
              {t("emptyWorkspaces.lead")}
            </p>
            <Button asChild variant="primary" className="mt-6">
              <Link href="/workspaces?new=1">{t("emptyWorkspaces.action")}</Link>
            </Button>
          </div>
        ) : (
          <>
            {showForm ? (
              <NewChatForm
                workspaces={availableWorkspaces}
                initialWorkspaceId={initialWorkspaceId}
                autoFocus={isFormOpen && !isUnfilteredEmpty}
                onCancel={isUnfilteredEmpty ? undefined : closeForm}
                className="mt-8"
              />
            ) : null}

            {availableWorkspaces.length > 1 &&
            (activeFilterWorkspaceId !== null || !isUnfilteredEmpty) ? (
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <label htmlFor={filterId} className="text-ink-soft text-sm font-medium">
                  {t("filter.label")}
                </label>
                <select
                  id={filterId}
                  value={activeFilterWorkspaceId ?? ""}
                  onChange={(event) =>
                    setFilterWorkspaceId(event.target.value === "" ? null : event.target.value)
                  }
                  className="border-rule-strong bg-sheet text-ink focus-visible:outline-pen rounded-control h-9 border px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  <option value="">{t("filter.all")}</option>
                  {availableWorkspaces.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <SessionList
              workspaceId={activeFilterWorkspaceId}
              focusAfterDelete={headingRef}
              isFiltered={activeFilterWorkspaceId !== null}
              hideWhenEmpty={showForm}
              className="mt-6"
            />
          </>
        )}
      </div>
    </div>
  );
}
