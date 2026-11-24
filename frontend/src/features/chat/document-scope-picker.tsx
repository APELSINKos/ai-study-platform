"use client";

import { useTranslations } from "next-intl";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { documentErrorMessage } from "@/features/documents/error-message";
import { useWorkspaceDocuments } from "@/features/documents/hooks";
import type { DocumentOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export type ScopeMode = "all" | "selected";

/**
 * Intersects chosen scope document IDs with currently existing workspace documents once all pages
 * are loaded, converting an empty selection into `null` (all ready documents).
 */
export function reconcileScopeDocumentIds(
  selectedIds: readonly string[],
  existingDocuments: readonly DocumentOut[],
  hasUnloadedPages: boolean,
): string[] | null {
  if (hasUnloadedPages) {
    return selectedIds.length === 0 ? null : [...selectedIds];
  }
  const existingIds = new Set(existingDocuments.map((doc) => doc.id));
  const valid = selectedIds.filter((id) => existingIds.has(id));
  return valid.length === 0 ? null : valid;
}

interface DocumentScopePickerProps {
  workspaceId: string;
  scopeMode: ScopeMode;
  onScopeModeChange: (mode: ScopeMode) => void;
  selectedIds: readonly string[];
  onSelectedIdsChange: (nextIds: string[]) => void;
  maxScopeDocuments: number;
  autoFocus?: boolean;
  validationError?: string | null;
  className?: string;
}

/**
 * Chooses between all ready documents of a workspace and a checked subset, loading more pages on
 * demand and capping the selection at `/meta`'s `max_scope_documents`.
 */
export function DocumentScopePicker({
  workspaceId,
  scopeMode,
  onScopeModeChange,
  selectedIds,
  onSelectedIdsChange,
  maxScopeDocuments,
  autoFocus = false,
  validationError = null,
  className,
}: DocumentScopePickerProps) {
  const t = useTranslations("Chat.form");
  const tDocErrors = useTranslations("Documents.errors");
  const radioName = useId();
  const documents = useWorkspaceDocuments(workspaceId);
  const loadedDocs = documents.data?.documents ?? [];
  const readyDocs = loadedDocs.filter((doc) => doc.status === "ready");

  // Drop deleted IDs from the displayed count once all workspace pages are known.
  const existingIds = new Set(loadedDocs.map((doc) => doc.id));
  const effectiveSelectedIds =
    documents.data !== undefined && !documents.hasNextPage
      ? selectedIds.filter((id) => existingIds.has(id))
      : selectedIds;
  const selectedSet = new Set(effectiveSelectedIds);
  const atLimit = effectiveSelectedIds.length >= maxScopeDocuments;

  function toggleDocument(documentId: string, checked: boolean) {
    if (checked) {
      if (selectedSet.has(documentId) || atLimit) {
        return;
      }
      onSelectedIdsChange([...effectiveSelectedIds, documentId]);
    } else {
      onSelectedIdsChange(effectiveSelectedIds.filter((id) => id !== documentId));
    }
  }

  return (
    <fieldset className={cn("flex flex-col gap-3", className)}>
      <legend className="text-ink text-sm font-medium">{t("scopeLegend")}</legend>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <label className="text-ink inline-flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="radio"
            name={radioName}
            checked={scopeMode === "all"}
            autoFocus={autoFocus && scopeMode === "all"}
            onChange={() => onScopeModeChange("all")}
            className="accent-pen focus-visible:outline-pen size-4 focus-visible:outline-2 focus-visible:outline-offset-2"
          />
          <span>{t("scopeAll")}</span>
        </label>
        <label className="text-ink inline-flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="radio"
            name={radioName}
            checked={scopeMode === "selected"}
            autoFocus={autoFocus && scopeMode === "selected"}
            onChange={() => onScopeModeChange("selected")}
            className="accent-pen focus-visible:outline-pen size-4 focus-visible:outline-2 focus-visible:outline-offset-2"
          />
          <span>{t("scopeSelected")}</span>
        </label>
      </div>

      {scopeMode === "all" &&
      documents.data !== undefined &&
      readyDocs.length === 0 &&
      !documents.hasNextPage ? (
        <p className="text-ink-soft text-xs">{t("scopeEmpty")}</p>
      ) : null}

      {scopeMode === "selected" ? (
        <div className="border-rule rounded-control bg-paper/50 flex flex-col gap-3 border p-3">
          {documents.isPending ? (
            <p aria-busy="true" className="text-ink-soft text-sm">
              {t("documentsLoading")}
            </p>
          ) : documents.data === undefined ? (
            <div className="flex flex-col items-start gap-2">
              <p role="alert" className="text-margin text-sm">
                {documentErrorMessage(documents.error, "load", tDocErrors)}
              </p>
              <Button
                variant="secondary"
                size="sm"
                isLoading={documents.isFetching}
                onClick={() => void documents.refetch()}
              >
                {t("documentsRetry")}
              </Button>
            </div>
          ) : (
            <>
              {readyDocs.length === 0 ? (
                <p className="text-ink-soft text-sm">{t("scopeNoReadyForSelection")}</p>
              ) : (
                <>
                  <div className="text-ink-soft flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
                    <span>{t("scopeSelectedCount", { count: effectiveSelectedIds.length })}</span>
                    <span>{t("scopeLimitHint", { max: maxScopeDocuments })}</span>
                  </div>
                  <ul className="divide-rule max-h-56 divide-y overflow-y-auto pr-1">
                    {readyDocs.map((doc) => {
                      const isChecked = selectedSet.has(doc.id);
                      const isDisabled = !isChecked && atLimit;
                      const label = doc.title ?? doc.original_filename;
                      return (
                        <li key={doc.id} className="py-2 first:pt-0 last:pb-0">
                          <label
                            className={cn(
                              "flex items-start gap-2.5 text-sm",
                              isDisabled
                                ? "text-ink-soft cursor-not-allowed"
                                : "text-ink cursor-pointer",
                            )}
                          >
                            <input
                              type="checkbox"
                              checked={isChecked}
                              disabled={isDisabled}
                              onChange={(event) => toggleDocument(doc.id, event.target.checked)}
                              className="accent-pen focus-visible:outline-pen mt-0.5 size-4 shrink-0 focus-visible:outline-2 focus-visible:outline-offset-2"
                            />
                            <span className="min-w-0 break-words">{label}</span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
              {documents.hasNextPage ? (
                <div className="flex flex-wrap items-center gap-3 pt-1">
                  <Button
                    variant="secondary"
                    size="sm"
                    isLoading={documents.isFetchingNextPage}
                    onClick={() => void documents.fetchNextPage()}
                  >
                    {t("documentsShowMore")}
                  </Button>
                  {documents.isFetchNextPageError ? (
                    <p role="alert" className="text-margin text-xs">
                      {documentErrorMessage(documents.error, "loadMore", tDocErrors)}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}

      {validationError ? (
        <p role="alert" className="text-margin text-xs">
          {validationError}
        </p>
      ) : null}
    </fieldset>
  );
}
