import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";

import type { Locale } from "@/i18n/config";

import en from "../../messages/en.json";
import ru from "../../messages/ru.json";

const catalogs = { en, ru } satisfies Record<Locale, typeof en>;

interface IntlRenderOptions extends Omit<RenderOptions, "wrapper"> {
  locale?: Locale;
  /** By default a new client that never retries a failed request. */
  queryClient?: QueryClient;
}

export function renderWithIntl(
  ui: ReactElement,
  {
    locale = "en",
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    ...options
  }: IntlRenderOptions = {},
): RenderResult & { queryClient: QueryClient } {
  // A wrapper rather than part of `ui`, so that `rerender` keeps the messages and the cache.
  function Providers({ children }: { children: ReactNode }) {
    return (
      <NextIntlClientProvider locale={locale} messages={catalogs[locale]}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </NextIntlClientProvider>
    );
  }
  const result = render(ui, { ...options, wrapper: Providers });
  return { ...result, queryClient };
}
