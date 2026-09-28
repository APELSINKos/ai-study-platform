"use client";

import { useTranslations } from "next-intl";

import { useCurrentUser } from "@/features/auth/hooks";

export function DashboardGreeting() {
  const t = useTranslations("Dashboard");
  const { data: user } = useCurrentUser();

  if (!user) {
    return (
      <>
        <h1 className="sr-only">{t("metaTitle")}</h1>
        <div aria-hidden className="bg-ink/10 h-10 w-64 animate-pulse rounded" />
      </>
    );
  }

  return (
    <h1 className="font-display text-title font-semibold">
      {t("greeting", { name: user.display_name })}
    </h1>
  );
}
