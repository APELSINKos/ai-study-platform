"use client";

import { WarningIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { SiteHeader } from "@/components/site-header";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("ErrorPage");

  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="px-4 py-6 sm:px-8 sm:py-12">
      <div className="notebook mx-auto max-w-5xl">
        <SiteHeader />
        <main className="notebook-row mt-16 sm:mt-24">
          <p className="margin-note">{t("marginNote")}</p>
          <div>
            <WarningIcon aria-hidden className="text-margin size-10" />
            <h1 className="font-display text-title mt-4 font-semibold">{t("title")}</h1>
            <p className="text-ink-soft mt-4 max-w-[58ch] text-lg leading-8">{t("lead")}</p>
            {error.digest ? (
              <p className="text-ink-soft mt-4 text-xs">{t("reference", { id: error.digest })}</p>
            ) : null}
            <div className="mt-8 flex gap-3">
              <Button variant="primary" onClick={reset}>
                {t("retry")}
              </Button>
              <Button asChild variant="secondary">
                <Link href="/">{t("home")}</Link>
              </Button>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
