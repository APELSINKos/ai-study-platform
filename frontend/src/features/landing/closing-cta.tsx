import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

export function ClosingCta() {
  const t = useTranslations("Landing");

  return (
    <section aria-labelledby="closing-title" className="notebook-row mt-32 sm:mt-44">
      <div>
        <h2 id="closing-title" className="font-display text-headline font-semibold text-balance">
          {t("closing.title")}
        </h2>
        <p className="text-ink-soft mt-4 max-w-[48ch] text-lg leading-8">{t("closing.body")}</p>
        <div className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-4">
          <Button asChild variant="primary" size="lg">
            <Link href="/register">{t("cta.createAccount")}</Link>
          </Button>
          <Button asChild variant="link" className="text-base">
            <Link href="/login">{t("cta.signIn")}</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
