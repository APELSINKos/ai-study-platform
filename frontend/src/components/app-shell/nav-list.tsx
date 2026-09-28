"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import { NAV_ITEMS } from "./nav-items";

/** The same destination list backs the desktop rail and the mobile drawer. */
export function NavList({
  onNavigate,
  className,
}: {
  onNavigate?: () => void;
  className?: string;
}) {
  const t = useTranslations("AppShell.nav");
  const pathname = usePathname();

  return (
    <ul className={cn("flex flex-col gap-1", className)}>
      {NAV_ITEMS.map(({ href, labelKey, Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <li key={href} className="relative">
            {active ? (
              <span
                aria-hidden
                className="bg-margin absolute top-1 bottom-1 left-0 w-0.5 rounded-full"
              />
            ) : null}
            <Link
              href={href}
              aria-current={active ? "page" : undefined}
              onClick={onNavigate}
              className={cn(
                "rounded-control flex items-center gap-2 px-3 py-2 text-sm font-medium transition-colors",
                active ? "text-ink bg-ink/5" : "text-ink-soft hover:text-ink hover:bg-ink/5",
              )}
            >
              <Icon aria-hidden className="size-4" weight={active ? "fill" : "regular"} />
              {t(labelKey)}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
