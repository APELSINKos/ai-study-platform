"use client";

import { useTranslations } from "next-intl";
import type { ReactElement, ReactNode, RefObject } from "react";

import { AlertDialog } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import type { DocumentOut } from "@/lib/api/types";

import {
  DOCUMENT_NOT_FOUND_CODE,
  DOCUMENT_NOT_RETRYABLE_CODE,
  documentErrorMessage,
} from "./error-message";
import { useRetryDocument } from "./hooks";

function hasCode(error: unknown, code: string): boolean {
  return error instanceof ApiError && error.code === code;
}

interface RetryProcessingButtonProps {
  document: DocumentOut;
  label: string;
  /** Names the file for screen readers where the label alone does not say which one. */
  ariaLabel?: string;
  /** Shown before the label while no retry is running. */
  icon?: ReactNode;
  className?: string;
  /**
   * Runs once the document is on its way again, through this retry or another one, which takes
   * this button away.
   */
  onRetried: () => void;
  /** Runs when the document turns out to be deleted, which takes this button away with it. */
  onGone: () => void;
}

/**
 * Starts processing a failed or stalled document again, for its row and for its page. A refused
 * retry is explained last in the surrounding row of controls, so the sentence sits under them.
 */
export function RetryProcessingButton({
  document,
  label,
  ariaLabel,
  icon,
  className,
  onRetried,
  onGone,
}: RetryProcessingButtonProps) {
  const tErrors = useTranslations("Documents.errors");
  const retry = useRetryDocument(document);

  function retryProcessing() {
    retry.mutate(undefined, {
      // The button goes away once the document is on its way again, so the caller moves focus.
      onSuccess: (updated) => {
        if (!updated.can_retry) {
          onRetried();
        }
      },
      // These refusals take the button away too, once the refresh after every retry lands.
      onError: (error) => {
        if (hasCode(error, DOCUMENT_NOT_RETRYABLE_CODE)) {
          onRetried();
        } else if (hasCode(error, DOCUMENT_NOT_FOUND_CODE)) {
          onGone();
        }
      },
    });
  }

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        isLoading={retry.isPending}
        aria-label={ariaLabel}
        className={className}
        onClick={retryProcessing}
      >
        {retry.isPending ? null : icon}
        {label}
      </Button>
      {retry.isError ? (
        <p role="alert" className="text-margin order-last basis-full text-sm">
          {documentErrorMessage(retry.error, "retry", tErrors)}
        </p>
      ) : null}
    </>
  );
}

interface DeleteDocumentDialogProps {
  document: DocumentOut;
  /** The button that opens the question. */
  trigger: ReactElement;
  /** Deletes the document; the question stays open until the delete settles. */
  onConfirm: () => Promise<unknown>;
  /** Where focus goes after the delete when the trigger went with the document. */
  focusAfterConfirm?: RefObject<HTMLElement | null>;
}

/** Asks before a document is deleted, naming its file, and says why a delete failed. */
export function DeleteDocumentDialog({
  document,
  trigger,
  onConfirm,
  focusAfterConfirm,
}: DeleteDocumentDialogProps) {
  const t = useTranslations("Documents.deleteDialog");
  const tErrors = useTranslations("Documents.errors");

  return (
    <AlertDialog
      trigger={trigger}
      title={t("title")}
      description={t("description", { filename: document.original_filename })}
      confirmLabel={t("confirm")}
      onConfirm={onConfirm}
      errorMessage={(error) => documentErrorMessage(error, "delete", tErrors)}
      focusAfterConfirm={focusAfterConfirm}
    />
  );
}
