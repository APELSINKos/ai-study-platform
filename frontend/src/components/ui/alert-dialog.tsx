"use client";

import { useTranslations } from "next-intl";
import { AlertDialog as AlertDialogPrimitive } from "radix-ui";
import { useState, type ReactElement } from "react";

import { Button } from "./button";
import { IndexCardBody, IndexCardHeader } from "./index-card";

interface AlertDialogProps {
  /** The control that opens the dialog; focus returns to it when the dialog closes. */
  trigger: ReactElement;
  title: string;
  description: string;
  confirmLabel: string;
  /** Runs the confirmed action. The dialog stays open until it settles and closes on success. */
  onConfirm: () => Promise<unknown>;
  /** Turns a failure of `onConfirm` into the translated sentence shown inside the dialog. */
  errorMessage: (error: unknown) => string;
}

/** Asks before a destructive action and keeps the question on screen until the action is done. */
export function AlertDialog({
  trigger,
  title,
  description,
  confirmLabel,
  onConfirm,
  errorMessage,
}: AlertDialogProps) {
  const t = useTranslations("AlertDialog");
  const [open, setOpen] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleOpenChange(nextOpen: boolean) {
    // Escape and Cancel must not abandon an action that has already been sent.
    if (isPending) {
      return;
    }
    setOpen(nextOpen);
    setError(null);
  }

  async function handleConfirm() {
    if (isPending) {
      return;
    }
    setIsPending(true);
    setError(null);
    try {
      await onConfirm();
      setOpen(false);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setIsPending(false);
    }
  }

  return (
    <AlertDialogPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      <AlertDialogPrimitive.Trigger asChild>{trigger}</AlertDialogPrimitive.Trigger>
      <AlertDialogPrimitive.Portal>
        <AlertDialogPrimitive.Overlay className="bg-ink/30 fixed inset-0 z-40" />
        <AlertDialogPrimitive.Content className="index-card fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto">
          <IndexCardHeader>
            <AlertDialogPrimitive.Title className="font-display text-xl font-semibold break-words">
              {title}
            </AlertDialogPrimitive.Title>
          </IndexCardHeader>
          <IndexCardBody className="flex flex-col gap-4">
            <AlertDialogPrimitive.Description className="text-ink-soft text-sm break-words">
              {description}
            </AlertDialogPrimitive.Description>
            {error ? (
              <p role="alert" className="text-margin text-sm">
                {error}
              </p>
            ) : null}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <AlertDialogPrimitive.Cancel asChild>
                <Button variant="ghost">{t("cancel")}</Button>
              </AlertDialogPrimitive.Cancel>
              <Button variant="danger" isLoading={isPending} onClick={handleConfirm}>
                {confirmLabel}
              </Button>
            </div>
          </IndexCardBody>
        </AlertDialogPrimitive.Content>
      </AlertDialogPrimitive.Portal>
    </AlertDialogPrimitive.Root>
  );
}
