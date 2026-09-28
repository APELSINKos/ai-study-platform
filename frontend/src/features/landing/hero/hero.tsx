import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

import { LecturePage } from "./lecture-page";

export function Hero() {
  const t = useTranslations("Landing");

  return (
    <section aria-labelledby="hero-title" className="notebook-row mt-16 sm:mt-24">
      <div>
        {/* Each sentence starts its own line; a long one still wraps evenly within it. */}
        <h1 id="hero-title" className="font-display text-display font-semibold text-balance">
          {t.rich("hero.headline", {
            line: (chunks) => <span className="block">{chunks}</span>,
          })}
        </h1>
        <div className="mt-10 grid items-start gap-14 lg:mt-14 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
          <div>
            <p className="text-ink-soft max-w-[46ch] text-lg leading-8">{t("hero.lead")}</p>
            <div className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-4">
              <Button asChild variant="primary" size="lg">
                <Link href="/register">{t("cta.createAccount")}</Link>
              </Button>
              <Button asChild variant="link" className="text-base">
                <Link href="/login">{t("cta.signIn")}</Link>
              </Button>
            </div>
          </div>
          <LecturePage />
        </div>
      </div>
    </section>
  );
}
