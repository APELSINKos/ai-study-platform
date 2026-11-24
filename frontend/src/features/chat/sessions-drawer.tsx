"use client";

import { ListIcon, PlusIcon, XIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Dialog, VisuallyHidden } from "radix-ui";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import { SessionList } from "./session-list";

interface SessionsDrawerProps {
  activeSessionId: string;
  onDeletingActiveSession?: () => void;
  onDeleteActiveSessionError?: () => void;
}

/** Slide-over drawer for switching chats or starting a new one without cramping the reading column. */
export function SessionsDrawer({
  activeSessionId,
  onDeletingActiveSession,
  onDeleteActiveSessionError,
}: SessionsDrawerProps) {
  const t = useTranslations("Chat.session");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const titleRef = useRef<HTMLHeadingElement>(null);

  function handleDeletingSession(deletingId: string) {
    if (deletingId === activeSessionId) {
      onDeletingActiveSession?.();
    }
  }

  function handleDeleteSessionError(failedId: string) {
    if (failedId === activeSessionId) {
      onDeleteActiveSessionError?.();
    }
  }

  function handleDeletedSession(deletedId: string) {
    if (deletedId === activeSessionId) {
      setOpen(false);
      router.replace("/chat");
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="secondary" size="sm">
          <ListIcon aria-hidden />
          {t("sessionsButton")}
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="bg-scrim fixed inset-0 z-40" />
        <Dialog.Content className="bg-sheet fixed inset-y-0 left-0 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-4 p-4 shadow-[var(--shadow-raised)]">
          <VisuallyHidden.Root asChild>
            <Dialog.Description>{t("drawer.description")}</Dialog.Description>
          </VisuallyHidden.Root>
          <div className="flex items-center justify-between gap-2">
            <Dialog.Title
              ref={titleRef}
              tabIndex={-1}
              className="font-display text-xl font-semibold"
            >
              {t("drawer.title")}
            </Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label={t("drawer.close")}>
                <XIcon aria-hidden className="size-5" />
              </Button>
            </Dialog.Close>
          </div>
          <Button asChild variant="secondary" size="sm" className="w-full justify-center">
            <Link href="/chat" onClick={() => setOpen(false)}>
              <PlusIcon aria-hidden />
              {t("drawer.newChat")}
            </Link>
          </Button>
          <div className="border-rule flex-1 overflow-y-auto border-t pt-2">
            <SessionList
              workspaceId={null}
              activeSessionId={activeSessionId}
              focusAfterDelete={titleRef}
              onSelectSession={() => setOpen(false)}
              onDeletingSession={handleDeletingSession}
              onDeleteSessionError={handleDeleteSessionError}
              onDeletedSession={handleDeletedSession}
              variant="drawer"
            />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
