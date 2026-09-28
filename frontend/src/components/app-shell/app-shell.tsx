"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { useCurrentUser } from "@/features/auth/hooks";

import { MobileNav } from "./mobile-nav";
import { NavList } from "./nav-list";
import { UserMenu } from "./user-menu";

export function AppShell({ children }: { children: ReactNode }) {
  const t = useTranslations("AppShell.nav");
  const { data: user } = useCurrentUser();

  return (
    <div className="md:grid md:grid-cols-[16rem_1fr]">
      <aside className="border-rule bg-sheet hidden flex-col justify-between border-r p-4 md:flex md:min-h-screen">
        <div className="flex flex-col gap-8">
          <Link href="/dashboard" className="font-display px-1 text-xl font-semibold">
            Recall
          </Link>
          <nav aria-label={t("label")}>
            <NavList />
          </nav>
        </div>
        <div className="border-rule flex flex-col gap-4 border-t pt-4">
          <div className="flex items-center gap-2">
            <LocaleSwitcher />
            <ThemeToggle />
          </div>
          <UserMenu user={user} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="border-rule bg-sheet flex items-center justify-between border-b p-4 md:hidden">
          <Link href="/dashboard" className="font-display text-xl font-semibold">
            Recall
          </Link>
          <div className="flex items-center gap-2">
            <LocaleSwitcher />
            <ThemeToggle />
            <MobileNav user={user} />
          </div>
        </header>

        <main className="px-4 py-6 sm:px-8 sm:py-12">
          <div className="notebook mx-auto max-w-5xl">
            <div>{children}</div>
          </div>
        </main>
      </div>
    </div>
  );
}
