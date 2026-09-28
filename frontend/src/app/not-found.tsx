import { CompassIcon } from "@phosphor-icons/react/ssr";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Button } from "@/components/ui/button";
import { SiteHeader } from "@/components/site-header";

export default async function NotFound() {
  const t = await getTranslations("NotFound");

  return (
    <div className="px-4 py-6 sm:px-8 sm:py-12">
      <div className="notebook mx-auto max-w-5xl">
        <SiteHeader />
        <main className="notebook-row mt-16 sm:mt-24">
          <p className="margin-note">{t("marginNote")}</p>
          <div>
            <CompassIcon aria-hidden className="text-pen size-10" />
            <h1 className="font-display text-title mt-4 font-semibold">{t("title")}</h1>
            <p className="text-ink-soft mt-4 max-w-[58ch] text-lg leading-8">{t("lead")}</p>
            <Button asChild variant="primary" className="mt-8">
              <Link href="/">{t("home")}</Link>
            </Button>
          </div>
        </main>
      </div>
    </div>
  );
}
