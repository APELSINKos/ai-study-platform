import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import type { Locale } from "@/i18n/config";
import {
  ApiError,
  HTTP_ERROR_CODE,
  INVALID_RESPONSE_CODE,
  NETWORK_ERROR_CODE,
} from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { searchErrorMessage } from "./error-message";

function Probe({ error }: { error: unknown }) {
  const t = useTranslations("Search.errors");
  return <p>{searchErrorMessage(error, t)}</p>;
}

function messageFor(error: unknown, locale: Locale = "en"): string {
  const { unmount } = renderWithIntl(<Probe error={error} />, { locale });
  const text = screen.getByRole("paragraph").textContent ?? "";
  unmount();
  return text;
}

function apiError(status: number, code: string, retryAfterSeconds: number | null = null) {
  return new ApiError({ status, code, message: "The backend's own English.", retryAfterSeconds });
}

describe("searchErrorMessage", () => {
  it("asks to check the connection when the API cannot be reached", () => {
    expect(messageFor(apiError(0, NETWORK_ERROR_CODE))).toBe(
      "The API could not be reached. Check your connection and try again.",
    );
  });

  it.each(["not_authenticated", "token_expired", "invalid_token"])(
    "asks to sign in again after %s",
    (code) => {
      expect(messageFor(apiError(401, code))).toBe(
        "Your session has ended. Sign in again to continue.",
      );
    },
  );

  it("says the workspace is gone", () => {
    expect(messageFor(apiError(404, "workspace_not_found"))).toBe(
      "This workspace no longer exists.",
    );
  });

  it("asks for another query when the API refuses this one", () => {
    expect(messageFor(apiError(422, "validation_error"))).toBe(
      "This query cannot be searched. Shorten it or remove unusual characters.",
    );
  });

  it.each([
    [1, "Too many searches. Try again in 1 second."],
    [30, "Too many searches. Try again in 30 seconds."],
    [59, "Too many searches. Try again in 59 seconds."],
    [60, "Too many searches. Try again in 1 minute."],
    [61, "Too many searches. Try again in 2 minutes."],
    [1800, "Too many searches. Try again in 30 minutes."],
  ] as const)("names the wait of %i seconds when rate limited", (seconds, expected) => {
    expect(messageFor(apiError(429, "rate_limited", seconds))).toBe(expected);
  });

  it("falls back to a moment when a rate limit names no wait", () => {
    expect(messageFor(apiError(429, "rate_limited"))).toBe(
      "Too many searches. Try again in a moment.",
    );
  });

  it.each([
    // Only a search by embeddings alone is refused for this; the page never asks for one.
    ["search_unavailable", 503],
    ["internal_error", 500],
    [HTTP_ERROR_CODE, 502],
    [INVALID_RESPONSE_CODE, 200],
    ["something_new", 418],
  ] as const)("says the search failed after %s", (code, status) => {
    expect(messageFor(apiError(status, code))).toBe("Search failed. Try again.");
  });

  it("says the search failed after a failure that is no API error", () => {
    expect(messageFor(new Error("boom"))).toBe("Search failed. Try again.");
  });

  it("never shows the backend's English", () => {
    messageFor(apiError(500, "internal_error"));

    expect(screen.queryByText("The backend's own English.")).not.toBeInTheDocument();
  });

  it.each([
    [1, "Слишком много поисковых запросов. Повторите через 1 секунду."],
    [2, "Слишком много поисковых запросов. Повторите через 2 секунды."],
    [5, "Слишком много поисковых запросов. Повторите через 5 секунд."],
    [11, "Слишком много поисковых запросов. Повторите через 11 секунд."],
    [21, "Слишком много поисковых запросов. Повторите через 21 секунду."],
  ] as const)("names a wait of %i seconds in Russian", (seconds, expected) => {
    expect(messageFor(apiError(429, "rate_limited", seconds), "ru")).toBe(expected);
  });

  it.each([
    [60, "Слишком много поисковых запросов. Повторите через 1 минуту."],
    [120, "Слишком много поисковых запросов. Повторите через 2 минуты."],
    [300, "Слишком много поисковых запросов. Повторите через 5 минут."],
    [660, "Слишком много поисковых запросов. Повторите через 11 минут."],
    [1260, "Слишком много поисковых запросов. Повторите через 21 минуту."],
  ] as const)("names a wait of %i seconds in minutes in Russian", (seconds, expected) => {
    expect(messageFor(apiError(429, "rate_limited", seconds), "ru")).toBe(expected);
  });

  it("speaks Russian", () => {
    expect(messageFor(apiError(0, NETWORK_ERROR_CODE), "ru")).toBe(
      "Не удалось связаться с API. Проверьте соединение и попробуйте снова.",
    );
    expect(messageFor(apiError(401, "token_expired"), "ru")).toBe(
      "Сеанс завершился. Войдите снова, чтобы продолжить.",
    );
    expect(messageFor(apiError(404, "workspace_not_found"), "ru")).toBe(
      "Этого пространства больше нет.",
    );
    expect(messageFor(apiError(422, "validation_error"), "ru")).toBe(
      "По такому запросу искать нельзя. Сократите его или уберите необычные символы.",
    );
    expect(messageFor(apiError(429, "rate_limited"), "ru")).toBe(
      "Слишком много поисковых запросов. Повторите чуть позже.",
    );
    expect(messageFor(apiError(503, "search_unavailable"), "ru")).toBe(
      "Поиск не удался. Попробуйте ещё раз.",
    );
  });
});
