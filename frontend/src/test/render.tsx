import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";

import type { Locale } from "@/i18n/config";

import en from "../../messages/en.json";
import ru from "../../messages/ru.json";

const catalogs = { en, ru } satisfies Record<Locale, typeof en>;

interface IntlRenderOptions extends RenderOptions {
  locale?: Locale;
}

export function renderWithIntl(
  ui: ReactElement,
  { locale = "en", ...options }: IntlRenderOptions = {},
): RenderResult {
  return render(
    <NextIntlClientProvider locale={locale} messages={catalogs[locale]}>
      {ui}
    </NextIntlClientProvider>,
    options,
  );
}
