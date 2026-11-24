"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { IndexCard } from "@/components/ui/index-card";
import { workspaceErrorMessage } from "@/features/workspaces/error-message";
import { useWorkspaceList } from "@/features/workspaces/hooks";
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
 * The `/chat` entry point. Keeps per-session message drafts across session switches and renders
 * either the session index, the not-found view for malformed session URLs, or one active session.
 */
export function ChatView({ sessionParam, initialWorkspaceId }: ChatViewProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const updateDraft = useCallback((sessionId: string, value: string) => {
    setDrafts((prev) => ({ ...prev, [sessionId]: value }));
  }, []);

  const restoreDraft = useCallback((sessionId: string, value: string) => {
    setDrafts((prev) => (prev[sessionId] ? prev : { ...prev, [sessionId]: value }));
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
        onDraftChange={(value) => updateDraft(sessionParam.id, value)}
        onRestoreDraft={restoreDraft}
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

  const hasWorkspaces = workspaces.data !== undefined && workspaces.data.length > 0;
  const sessions = useChatSessions(filterWorkspaceId, { enabled: hasWorkspaces });
  const focusHeadingOnArrival = useFocusOnArrival(workspaces.data !== undefined, headingRef);

  const isUnfilteredEmpty =
    hasWorkspaces && filterWorkspaceId === null && sessions.data?.length === 0;
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
          {hasWorkspaces && !showForm && !(filterWorkspaceId === null && sessions.isPending) ? (
            <Button ref={takeReturningFocus} variant="primary" onClick={() => setIsFormOpen(true)}>
              {t("newChat")}
            </Button>
          ) : null}
        </div>

        {workspaces.isPending ? (
          <IndexCard aria-busy="true" className="mt-8 p-6">
            <span className="sr-only">{t("list.loading")}</span>
            <div aria-hidden className="space-y-3">
              <div className="bg-ink/10 h-5 w-1/2 rounded motion-safe:animate-pulse" />
              <div className="bg-ink/10 h-4 w-2/3 rounded motion-safe:animate-pulse" />
            </div>
          </IndexCard>
        ) : workspaces.data === undefined ? (
          <div className="mt-8 flex flex-col items-start gap-4">
            <p role="alert" className="text-ink-soft text-sm">
              {workspaceErrorMessage(workspaces.error, "load", tWorkspaceErrors)}
            </p>
            <Button variant="secondary" isLoading={workspaces.isFetching} onClick={retryWorkspaces}>
              {t("list.retry")}
            </Button>
          </div>
        ) : workspaces.data.length === 0 ? (
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
                workspaces={workspaces.data}
                initialWorkspaceId={initialWorkspaceId}
                onCancel={isUnfilteredEmpty ? undefined : closeForm}
                className="mt-8"
              />
            ) : null}

            {workspaces.data.length > 1 && (filterWorkspaceId !== null || !isUnfilteredEmpty) ? (
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <label htmlFor={filterId} className="text-ink-soft text-sm font-medium">
                  {t("filter.label")}
                </label>
                <select
                  id={filterId}
                  value={filterWorkspaceId ?? ""}
                  onChange={(event) =>
                    setFilterWorkspaceId(event.target.value === "" ? null : event.target.value)
                  }
                  className="border-rule-strong bg-sheet text-ink focus-visible:outline-pen rounded-control h-9 border px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  <option value="">{t("filter.all")}</option>
                  {workspaces.data.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <SessionList
              workspaceId={filterWorkspaceId}
              focusAfterDelete={headingRef}
              isFiltered={filterWorkspaceId !== null}
              hideWhenEmpty={showForm}
              className="mt-6"
            />
          </>
        )}
      </div>
    </div>
  );
}
