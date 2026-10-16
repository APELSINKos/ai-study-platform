"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { useCreateWorkspace } from "./hooks";
import { toCreateRequest, type WorkspaceFormValues } from "./schemas";
import { WorkspaceForm } from "./workspace-form";

const EMPTY_VALUES: WorkspaceFormValues = { name: "", description: "", examDate: "" };

interface CreateWorkspaceFormProps {
  /** Offered when the page has something to return to; without it the form stays put. */
  onCancel?: () => void;
  /** Puts the cursor in the name field at once, for a form the user has just asked for. */
  autoFocus?: boolean;
  className?: string;
}

export function CreateWorkspaceForm({
  onCancel,
  autoFocus = false,
  className,
}: CreateWorkspaceFormProps) {
  const t = useTranslations("Workspaces.form");
  const router = useRouter();
  const create = useCreateWorkspace();
  // Still busy after success: the form stays until the new workspace's page replaces it, and a
  // second click in between must not create a second workspace.
  const isBusy = create.isPending || create.isSuccess;

  async function createAndOpen(values: WorkspaceFormValues) {
    const workspace = await create.mutateAsync(toCreateRequest(values));
    router.push(`/workspaces/${workspace.id}`);
  }

  return (
    <WorkspaceForm
      title={t("title")}
      submitLabel={t("submit")}
      submitVariant="primary"
      defaultValues={EMPTY_VALUES}
      isBusy={isBusy}
      onSubmit={createAndOpen}
      failedAction="create"
      onCancel={onCancel}
      autoFocus={autoFocus}
      className={className}
    />
  );
}
