import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
): RenderResult & { queryClient: QueryClient } {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <NextIntlClientProvider locale={locale} messages={catalogs[locale]}>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </NextIntlClientProvider>,
    options,
  );
  return { ...result, queryClient };
}
