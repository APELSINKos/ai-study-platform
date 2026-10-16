"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { WorkspaceOut } from "@/lib/api/types";

import { useUpdateWorkspace } from "./hooks";
import { toFormValues, toUpdateRequest, type WorkspaceFormValues } from "./schemas";
import { WorkspaceForm } from "./workspace-form";

interface EditWorkspaceFormProps {
  workspace: WorkspaceOut;
  /** Called once the changes are saved, or at once when there were none to save. */
  onSaved: () => void;
  onCancel: () => void;
  className?: string;
}

/** Changes the name, description and exam date of a workspace in place, on its own page. */
export function EditWorkspaceForm({
  workspace,
  onSaved,
  onCancel,
  className,
}: EditWorkspaceFormProps) {
  const t = useTranslations("Workspaces.edit");
  const update = useUpdateWorkspace(workspace.id);
  // What the form opened with: a refetch while it is open must not change what counts as edited.
  const [openedValues] = useState(() => toFormValues(workspace));

  async function save(values: WorkspaceFormValues) {
    const changes = toUpdateRequest(values, openedValues);
    if (changes) {
      await update.mutateAsync(changes);
    }
    onSaved();
  }

  return (
    <WorkspaceForm
      title={t("title")}
      submitLabel={t("submit")}
      submitVariant="secondary"
      defaultValues={openedValues}
      isBusy={update.isPending || update.isSuccess}
      onSubmit={save}
      failedAction="update"
      onCancel={onCancel}
      autoFocus
      className={className}
    />
  );
}
