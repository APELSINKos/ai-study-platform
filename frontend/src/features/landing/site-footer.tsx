import Link from "next/link";
import { useTranslations } from "next-intl";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { ThemeToggle } from "@/components/theme-toggle";

export function SiteFooter() {
  const t = useTranslations("Landing.footer");

  return (
    <footer className="notebook-row mt-28 sm:mt-36">
      <div className="border-rule flex flex-wrap items-center justify-between gap-x-8 gap-y-4 border-t pt-6">
        <div className="flex items-baseline gap-6">
          <span className="font-display text-xl font-semibold tracking-tight">Recall</span>
          <Link
            href="/status"
            className="text-ink-soft hover:text-ink rounded-control text-sm underline-offset-4 hover:underline"
          >
            {t("status")}
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <LocaleSwitcher />
          <ThemeToggle />
        </div>
      </div>
    </footer>
  );
}
