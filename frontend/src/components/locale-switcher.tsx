"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useTransition } from "react";

import { SegmentedButton, SegmentedGroup } from "@/components/ui/segmented";
import { setLocale } from "@/i18n/actions";
import { locales, type Locale } from "@/i18n/config";

export function LocaleSwitcher() {
  const t = useTranslations("Locale");
  const current = useLocale();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function choose(locale: Locale) {
    if (locale === current) {
      return;
    }
    startTransition(async () => {
      await setLocale(locale);
      router.refresh();
    });
  }

  return (
    <SegmentedGroup label={t("label")} busy={isPending}>
      {locales.map((locale) => (
        <SegmentedButton
          key={locale}
          lang={locale}
          title={t(locale)}
          pressed={locale === current}
          onClick={() => choose(locale)}
        >
          {locale.toUpperCase()}
        </SegmentedButton>
      ))}
    </SegmentedGroup>
  );
}
