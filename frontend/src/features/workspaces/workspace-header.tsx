"use client";

import { PencilSimpleIcon, TrashIcon } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import { AlertDialog } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import type { WorkspaceOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { EditWorkspaceForm } from "./edit-workspace-form";
import { workspaceErrorMessage } from "./error-message";
import { useDeleteWorkspace } from "./hooks";

/**
 * The workspace's name and description, with Edit and Delete beside the name. Edit swaps the
 * description for a form; the name stays as the page's heading meanwhile.
 */
export function WorkspaceHeader({
  workspace,
  className,
}: {
  workspace: WorkspaceOut;
  className?: string;
}) {
  const t = useTranslations("Workspaces.detail");
  const [isEditing, setIsEditing] = useState(false);
  // Set when the form closes, so that Edit takes the focus back when it reappears.
  const returnFocusRef = useRef(false);

  function closeForm() {
    returnFocusRef.current = true;
    setIsEditing(false);
  }

  function takeReturningFocus(button: HTMLButtonElement | null) {
    if (button && returnFocusRef.current) {
      returnFocusRef.current = false;
      button.focus();
    }
  }

  return (
    // A column that may shrink below the name's longest word, so that word breaks instead of
    // pushing the page sideways.
    <div
      className={cn(
        "grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-baseline",
        className,
      )}
    >
      <h1 className="font-display text-title font-semibold break-words">{workspace.name}</h1>
      {isEditing ? (
        <EditWorkspaceForm
          workspace={workspace}
          onSaved={closeForm}
          onCancel={closeForm}
          className="mt-2 sm:col-span-2"
        />
      ) : (
        <>
          {workspace.description ? (
            <p className="text-ink-soft max-w-[65ch] text-lg leading-8 break-words whitespace-pre-line sm:col-span-2">
              {workspace.description}
            </p>
          ) : null}
          {/* Beside the name on wider screens; on a phone, under the description. */}
          <div className="flex flex-wrap items-center gap-2 sm:col-start-2 sm:row-start-1 sm:justify-end">
            <Button
              ref={takeReturningFocus}
              variant="ghost"
              size="sm"
              // Under the description, the pencil lines up with the text instead of the padding.
              className="-ml-3 sm:ml-0"
              onClick={() => setIsEditing(true)}
            >
              <PencilSimpleIcon aria-hidden />
              {t("edit")}
            </Button>
            <DeleteWorkspaceButton workspace={workspace} />
          </div>
        </>
      )}
    </div>
  );
}

function DeleteWorkspaceButton({ workspace }: { workspace: WorkspaceOut }) {
  const t = useTranslations("Workspaces.detail");
  const tErrors = useTranslations("Workspaces.errors");
  const router = useRouter();
  const deletion = useDeleteWorkspace(workspace.id);

  async function deleteAndLeave() {
    await deletion.mutateAsync();
    // Replaced, so that Back does not return to the page of a workspace that is gone.
    router.replace("/workspaces");
  }

  return (
    <AlertDialog
      trigger={
        <Button variant="danger" size="sm">
          <TrashIcon aria-hidden />
          {t("delete")}
        </Button>
      }
      title={t("deleteDialog.title")}
      description={t("deleteDialog.description", {
        name: workspace.name,
        count: workspace.stats.document_count,
      })}
      confirmLabel={t("deleteDialog.confirm")}
      onConfirm={deleteAndLeave}
      errorMessage={(error) => workspaceErrorMessage(error, "delete", tErrors)}
    />
  );
}
