import { describe, expect, it } from "vitest";

import { isLocale, negotiateLocale, resolveLocale } from "./config";

describe("negotiateLocale", () => {
  it.each([
    [null, "en"],
    ["", "en"],
    ["ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7", "ru"],
    ["en-GB,en;q=0.9,ru;q=0.8", "en"],
    ["de-DE,de;q=0.9", "en"],
    ["de;q=1, ru;q=0.5", "ru"],
    ["en;q=0.2, ru;q=0.8", "ru"],
    ["ru;q=abc, en;q=0.1", "en"],
    ["ru;q=0", "en"],
    ["*", "en"],
  ] as const)("picks %j -> %s", (header, expected) => {
    expect(negotiateLocale(header)).toBe(expected);
  });
});

describe("resolveLocale", () => {
  it("prefers a supported cookie value", () => {
    expect(resolveLocale("ru", "en-US,en;q=0.9")).toBe("ru");
  });

  it.each(["de", "../../etc/passwd", "RU", ""])("ignores the unsupported cookie %j", (cookie) => {
    expect(resolveLocale(cookie, "ru-RU")).toBe("ru");
  });

  it("falls back to the default without cookie and header", () => {
    expect(resolveLocale(undefined, null)).toBe("en");
  });
});

describe("isLocale", () => {
  it("accepts only supported locales", () => {
    expect(isLocale("en")).toBe(true);
    expect(isLocale("ru")).toBe(true);
    expect(isLocale("de")).toBe(false);
    expect(isLocale(undefined)).toBe(false);
  });
});
