"use client";

import { useTranslations } from "next-intl";
import { AlertDialog as AlertDialogPrimitive } from "radix-ui";
import { useRef, useState, type ReactElement, type RefObject } from "react";

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
  /**
   * Where focus goes after the action succeeds, for an action that removes the trigger itself.
   * A dismissed dialog still returns focus to the trigger.
   */
  focusAfterConfirm?: RefObject<HTMLElement | null>;
}

/** Asks before a destructive action and keeps the question on screen until the action is done. */
export function AlertDialog({
  trigger,
  title,
  description,
  confirmLabel,
  onConfirm,
  errorMessage,
  focusAfterConfirm,
}: AlertDialogProps) {
  const t = useTranslations("AlertDialog");
  const [open, setOpen] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set once the action has succeeded, until the dialog has finished closing.
  const confirmedRef = useRef(false);

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
      confirmedRef.current = true;
      setOpen(false);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setIsPending(false);
    }
  }

  // Runs also when the dialog is unmounted together with a trigger the action removed.
  function handleCloseAutoFocus(event: Event) {
    const target = focusAfterConfirm?.current;
    if (confirmedRef.current && target) {
      event.preventDefault();
      target.focus();
    }
    confirmedRef.current = false;
  }

  return (
    <AlertDialogPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      <AlertDialogPrimitive.Trigger asChild>{trigger}</AlertDialogPrimitive.Trigger>
      <AlertDialogPrimitive.Portal>
        <AlertDialogPrimitive.Overlay className="bg-scrim fixed inset-0 z-40" />
        <AlertDialogPrimitive.Content
          onCloseAutoFocus={handleCloseAutoFocus}
          className="index-card fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto"
        >
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
