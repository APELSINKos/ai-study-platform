"use client";

import { ListIcon, XIcon } from "@phosphor-icons/react";
import { useTranslations } from "next-intl";
import { Dialog } from "radix-ui";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { UserOut } from "@/lib/api/types";

import { NavList } from "./nav-list";
import { UserMenu } from "./user-menu";

export function MobileNav({ user }: { user: UserOut | undefined }) {
  const t = useTranslations("AppShell.menu");
  const tNav = useTranslations("AppShell.nav");
  const [open, setOpen] = useState(false);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label={t("open")}>
          <ListIcon aria-hidden className="size-5" />
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="bg-ink/30 fixed inset-0 z-40" />
        <Dialog.Content className="bg-sheet fixed inset-y-0 left-0 z-50 flex w-72 flex-col gap-6 p-4 shadow-[var(--shadow-raised)]">
          <div className="flex items-center justify-between">
            <Dialog.Title className="font-display text-xl font-semibold">Recall</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label={t("close")}>
                <XIcon aria-hidden className="size-5" />
              </Button>
            </Dialog.Close>
          </div>
          <nav aria-label={tNav("label")} className="flex-1">
            <NavList onNavigate={() => setOpen(false)} />
          </nav>
          <UserMenu user={user} className="border-rule border-t pt-4" />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
