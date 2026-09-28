import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { DashboardGreeting } from "./greeting";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Dashboard");
  return { title: t("metaTitle") };
}

export default async function DashboardPage() {
  const t = await getTranslations("Dashboard");

  return (
    <div>
      <DashboardGreeting />
      <div className="index-card mt-8 max-w-xl">
        <div className="px-5 pt-5 pb-4 sm:px-6 sm:pt-6">
          <h2 className="font-display text-lg font-semibold">{t("emptyState.title")}</h2>
        </div>
        <p className="text-ink-soft px-5 pb-5 text-sm sm:px-6 sm:pb-6">{t("emptyState.body")}</p>
      </div>
    </div>
  );
}
