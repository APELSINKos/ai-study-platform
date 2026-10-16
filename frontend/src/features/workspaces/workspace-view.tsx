"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useId, useRef } from "react";

import { Button } from "@/components/ui/button";
import { DocumentList } from "@/features/documents/document-list";
import { ApiError } from "@/lib/api/errors";
import type { WorkspaceOut } from "@/lib/api/types";

import { workspaceErrorMessage, WORKSPACE_NOT_FOUND_CODE } from "./error-message";
import { useExamCountdown } from "./exam-countdown";
import { useWorkspace } from "./hooks";
import { WorkspaceHeader } from "./workspace-header";

// A malformed id fails validation before the backend looks for a workspace.
const MISSING_WORKSPACE_CODES: ReadonlySet<string> = new Set([
  WORKSPACE_NOT_FOUND_CODE,
  "validation_error",
]);

function isMissingWorkspace(error: unknown): boolean {
  return error instanceof ApiError && MISSING_WORKSPACE_CODES.has(error.code);
}

/** The page of one workspace, fetched in the browser: the server never sees the session. */
export function WorkspaceView({ id }: { id: string }) {
  const workspace = useWorkspace(id);

  // Checked before the data: a workspace deleted meanwhile is gone even if a copy is cached.
  if (isMissingWorkspace(workspace.error)) {
    return <WorkspaceNotFound />;
  }
  if (workspace.data !== undefined) {
    return <WorkspacePage workspace={workspace.data} />;
  }
  if (workspace.isPending) {
    return <WorkspaceSkeleton />;
  }
  return (
    <WorkspaceLoadError
      error={workspace.error}
      isRetrying={workspace.isFetching}
      onRetry={() => void workspace.refetch()}
    />
  );
}

function WorkspacePage({ workspace }: { workspace: WorkspaceOut }) {
  return (
    <div className="notebook-row">
      <WorkspaceMarginNote workspace={workspace} />
      <div className="max-w-3xl">
        <WorkspaceHeader workspace={workspace} />
        <WorkspaceDocuments workspace={workspace} className="mt-12" />
      </div>
    </div>
  );
}

/** The days left until the exam, or the number of documents when no exam date is set. */
function WorkspaceMarginNote({ workspace }: { workspace: WorkspaceOut }) {
  const t = useTranslations("Workspaces.detail");
  const countdown = useExamCountdown(workspace.exam_date);

  if (countdown) {
    return (
      <p className="margin-note flex flex-wrap gap-x-3 md:flex-col md:items-end">
        <span>{countdown.countdown}</span>
        <time dateTime={countdown.dateTime}>{countdown.date}</time>
      </p>
    );
  }
  return (
    <p className="margin-note">{t("documentCount", { count: workspace.stats.document_count })}</p>
  );
}

/** The region of the workspace's files: the upload drop zone, then the list of documents. */
function WorkspaceDocuments({
  workspace,
  className,
}: {
  workspace: WorkspaceOut;
  className?: string;
}) {
  const t = useTranslations("Workspaces.detail");
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  return (
    <section aria-labelledby={headingId} className={className}>
      {/* Focusable from code only: it takes the focus when a deleted document's row goes. */}
      <h2
        ref={headingRef}
        id={headingId}
        tabIndex={-1}
        className="font-display w-fit text-xl font-semibold"
      >
        {t("documentsTitle")}
      </h2>
      <DocumentList workspaceId={workspace.id} headingRef={headingRef} className="mt-2" />
    </section>
  );
}

function WorkspaceSkeleton() {
  const t = useTranslations("Workspaces.detail");
  return (
    <div className="notebook-row">
      <div aria-busy="true" className="max-w-3xl">
        <h1 className="sr-only">{t("metaTitle")}</h1>
        <p className="sr-only">{t("loading")}</p>
        <div aria-hidden>
          <div className="bg-ink/10 h-10 w-72 max-w-full rounded motion-safe:animate-pulse" />
          <div className="bg-ink/10 mt-5 h-5 w-full max-w-md rounded motion-safe:animate-pulse" />
        </div>
      </div>
    </div>
  );
}

function WorkspaceNotFound() {
  const t = useTranslations("Workspaces.detail.notFound");
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

interface WorkspaceLoadErrorProps {
  error: unknown;
  isRetrying: boolean;
  onRetry: () => void;
}

function WorkspaceLoadError({ error, isRetrying, onRetry }: WorkspaceLoadErrorProps) {
  const t = useTranslations("Workspaces.detail");
  const tErrors = useTranslations("Workspaces.errors");
  return (
    <div className="notebook-row">
      <div className="flex max-w-3xl flex-col items-start gap-4">
        <h1 className="sr-only">{t("metaTitle")}</h1>
        <p role="alert" className="text-ink-soft">
          {workspaceErrorMessage(error, "open", tErrors)}
        </p>
        <Button variant="secondary" isLoading={isRetrying} onClick={onRetry}>
          {t("retry")}
        </Button>
      </div>
    </div>
  );
}
