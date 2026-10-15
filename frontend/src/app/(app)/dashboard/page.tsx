import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { DashboardGreeting } from "@/features/dashboard/greeting";
import { DashboardMarginDate } from "@/features/dashboard/margin-date";
import { RecentWorkspaces } from "@/features/dashboard/recent-workspaces";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Dashboard");
  return { title: t("metaTitle") };
}

export default function DashboardPage() {
  return (
    <div className="notebook-row">
      <DashboardMarginDate />
      <div>
        <DashboardGreeting />
        <RecentWorkspaces className="mt-8 max-w-2xl" />
      </div>
    </div>
  );
}
