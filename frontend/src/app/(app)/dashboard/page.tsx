import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { IndexCard, IndexCardBody, IndexCardHeader } from "@/components/ui/index-card";
import { DashboardGreeting } from "@/features/dashboard/greeting";
import { DashboardMarginDate } from "@/features/dashboard/margin-date";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Dashboard");
  return { title: t("metaTitle") };
}

export default async function DashboardPage() {
  const t = await getTranslations("Dashboard");

  return (
    <div className="notebook-row">
      <DashboardMarginDate />
      <div>
        <DashboardGreeting />
        <IndexCard className="mt-8 max-w-xl">
          <IndexCardHeader>
            <h2 className="font-display text-lg font-semibold">{t("emptyState.title")}</h2>
          </IndexCardHeader>
          <IndexCardBody as="p" className="text-ink-soft pb-5 text-sm sm:pb-6">
            {t("emptyState.body")}
          </IndexCardBody>
        </IndexCard>
      </div>
    </div>
  );
}
