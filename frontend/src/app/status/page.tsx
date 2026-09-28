import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { SiteHeader } from "@/components/site-header";
import { SystemStatus } from "@/features/system-status/system-status";
import { READINESS_REFETCH_INTERVAL_MS } from "@/features/system-status/use-readiness";

const MS_PER_SECOND = 1000;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("StatusPage");
  return { title: t("metaTitle") };
}

export default async function StatusPage() {
  const t = await getTranslations("StatusPage");

  return (
    <div className="px-4 py-6 sm:px-8 sm:py-12">
      <div className="notebook mx-auto max-w-5xl">
        <SiteHeader />
        <main className="notebook-row mt-16 sm:mt-24">
          <p className="margin-note">
            {t("marginNote", { seconds: READINESS_REFETCH_INTERVAL_MS / MS_PER_SECOND })}
          </p>
          <div>
            <h1 className="font-display text-title font-semibold">{t("title")}</h1>
            <p className="text-ink-soft mt-4 max-w-[58ch] text-lg leading-8">{t("lead")}</p>
            <SystemStatus className="mt-12" />
          </div>
        </main>
      </div>
    </div>
  );
}
