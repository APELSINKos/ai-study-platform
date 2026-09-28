import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { SiteHeader } from "@/components/site-header";

export default async function AuthLayout({ children }: { children: ReactNode }) {
  const t = await getTranslations("Auth");

  return (
    <div className="px-4 py-6 sm:px-8 sm:py-12">
      <div className="notebook mx-auto max-w-3xl">
        <SiteHeader />
        <main className="notebook-row mt-16 sm:mt-24">
          <p className="margin-note">{t("marginNote")}</p>
          <div>{children}</div>
        </main>
      </div>
    </div>
  );
}
