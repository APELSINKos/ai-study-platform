"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { IndexCard, IndexCardBody, IndexCardHeader } from "@/components/ui/index-card";
import { useMeta } from "@/features/meta/hooks";
import type { WorkspaceOut } from "@/lib/api/types";

import { DocumentScopePicker, type ScopeMode } from "./document-scope-picker";
import { chatErrorMessage } from "./error-message";
import { useCreateChatSession } from "./hooks";

const DEFAULT_MAX_SCOPE_DOCUMENTS = 50;

interface NewChatFormProps {
  workspaces: WorkspaceOut[];
  initialWorkspaceId: string | null;
  autoFocus?: boolean;
  onCancel?: () => void;
  className?: string;
}

/**
 * Starts a new chat session scoped to one workspace (and optionally a checked subset of its
 * ready documents). Never creates a session on mount: the user always submits explicitly.
 */
export function NewChatForm({
  workspaces,
  initialWorkspaceId,
  autoFocus = false,
  onCancel,
  className,
}: NewChatFormProps) {
  const t = useTranslations("Chat.form");
  const tErrors = useTranslations("Chat.errors");
  const router = useRouter();
  const headingId = useId();
  const meta = useMeta().data;
  const createSession = useCreateChatSession();

  const [chosenWorkspaceId, setChosenWorkspaceId] = useState<string | null>(initialWorkspaceId);
  const [scopeMode, setScopeMode] = useState<ScopeMode>("all");
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [scopeValidationError, setScopeValidationError] = useState<string | null>(null);

  // Derived during render so a deleted or absent initial workspace falls back cleanly without
  // setState in an effect.
  const fallbackWorkspaceId =
    (initialWorkspaceId !== null && workspaces.some((w) => w.id === initialWorkspaceId)
      ? initialWorkspaceId
      : workspaces[0]?.id) ?? "";
  const selectedWorkspaceId =
    chosenWorkspaceId !== null && workspaces.some((w) => w.id === chosenWorkspaceId)
      ? chosenWorkspaceId
      : fallbackWorkspaceId;

  const maxScopeDocuments = meta?.chat.max_scope_documents ?? DEFAULT_MAX_SCOPE_DOCUMENTS;
  const isSubmitting = createSession.isPending || createSession.isSuccess;

  function handleWorkspaceChange(nextWorkspaceId: string) {
    setChosenWorkspaceId(nextWorkspaceId);
    setScopeMode("all");
    setSelectedDocIds([]);
    setScopeValidationError(null);
    createSession.reset();
  }

  function handleScopeModeChange(nextMode: ScopeMode) {
    setScopeMode(nextMode);
    setScopeValidationError(null);
    createSession.reset();
  }

  function handleSelectedIdsChange(nextIds: string[]) {
    setSelectedDocIds(nextIds);
    setScopeValidationError(null);
    createSession.reset();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting || selectedWorkspaceId === "") {
      return;
    }
    if (scopeMode === "selected" && selectedDocIds.length === 0) {
      setScopeValidationError(t("scopeSelectionRequired"));
      return;
    }
    setScopeValidationError(null);
    createSession.mutate(
      {
        workspace_id: selectedWorkspaceId,
        document_ids: scopeMode === "all" ? null : selectedDocIds,
      },
      {
        onSuccess: (created) => {
          router.push(`/chat?session=${created.id}`);
        },
      },
    );
  }

  return (
    <IndexCard className={className}>
      <IndexCardHeader>
        <h2 id={headingId} className="font-display text-xl font-semibold">
          {t("title")}
        </h2>
      </IndexCardHeader>
      <IndexCardBody
        as="form"
        aria-labelledby={headingId}
        onSubmit={handleSubmit}
        className="flex flex-col gap-5"
      >
        <Field label={t("workspaceLabel")}>
          <select
            value={selectedWorkspaceId}
            onChange={(event) => handleWorkspaceChange(event.target.value)}
            autoFocus={autoFocus}
            className="border-rule-strong bg-sheet text-ink focus-visible:outline-pen rounded-control h-10 w-full border px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
        </Field>

        {selectedWorkspaceId !== "" ? (
          <DocumentScopePicker
            workspaceId={selectedWorkspaceId}
            scopeMode={scopeMode}
            onScopeModeChange={handleScopeModeChange}
            selectedIds={selectedDocIds}
            onSelectedIdsChange={handleSelectedIdsChange}
            maxScopeDocuments={maxScopeDocuments}
            validationError={scopeValidationError}
          />
        ) : null}

        {createSession.error ? (
          <p role="alert" className="text-margin text-sm">
            {chatErrorMessage(createSession.error, "createSession", tErrors)}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" isLoading={isSubmitting}>
            {t("submit")}
          </Button>
          {onCancel ? (
            <Button variant="ghost" onClick={onCancel}>
              {t("cancel")}
            </Button>
          ) : null}
        </div>
      </IndexCardBody>
    </IndexCard>
  );
}
