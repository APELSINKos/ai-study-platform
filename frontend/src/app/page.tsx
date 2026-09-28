import { getTranslations } from "next-intl/server";

import { SiteHeader } from "@/components/site-header";

export default async function HomePage() {
  const t = await getTranslations("Home");

  return (
    <div className="px-4 py-6 sm:px-8 sm:py-12">
      <div className="notebook mx-auto max-w-5xl">
        <SiteHeader />
        <main className="notebook-row mt-16 sm:mt-24">
          <p className="margin-note">{t("marginNote")}</p>
          <div>
            {/* Each sentence starts its own line; a long one still wraps evenly within it. */}
            <h1 className="font-display text-display font-semibold text-balance">
              {t.rich("headline", {
                line: (chunks) => <span className="block">{chunks}</span>,
              })}
            </h1>
            <p className="text-ink-soft mt-8 max-w-[58ch] text-lg leading-8">{t("lead")}</p>
          </div>
        </main>
      </div>
    </div>
  );
}
