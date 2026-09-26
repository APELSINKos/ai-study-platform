export const locales = ["en", "ru"] as const;
export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";
export const LOCALE_COOKIE = "NEXT_LOCALE";
export const LOCALE_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

const MAX_QUALITY = 1;

interface LanguageRange {
  tag: string;
  quality: number;
  position: number;
}

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (locales as readonly string[]).includes(value);
}

/** Best supported locale for an Accept-Language header, honouring quality values. */
export function negotiateLocale(acceptLanguage: string | null | undefined): Locale {
  if (!acceptLanguage) {
    return defaultLocale;
  }
  const ranges = acceptLanguage
    .split(",")
    .map(parseLanguageRange)
    .filter((range): range is LanguageRange => range !== null && range.quality > 0)
    .sort((a, b) => b.quality - a.quality || a.position - b.position);

  for (const range of ranges) {
    const language = range.tag.split("-")[0]?.toLowerCase();
    if (isLocale(language)) {
      return language;
    }
  }
  return defaultLocale;
}

export function resolveLocale(
  cookieValue: string | undefined,
  acceptLanguage: string | null,
): Locale {
  return isLocale(cookieValue) ? cookieValue : negotiateLocale(acceptLanguage);
}

function parseLanguageRange(part: string, position: number): LanguageRange | null {
  const [rawTag, ...parameters] = part.split(";");
  const tag = rawTag?.trim();
  if (!tag) {
    return null;
  }
  let quality = MAX_QUALITY;
  for (const parameter of parameters) {
    const [name, value] = parameter.split("=").map((piece) => piece.trim());
    if (name === "q") {
      quality = Number(value);
      if (!Number.isFinite(quality) || quality < 0 || quality > MAX_QUALITY) {
        return null;
      }
    }
  }
  return { tag, quality, position };
}
