import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import type { Locale } from "@/i18n/config";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { chatErrorMessage, type ChatAction } from "./error-message";

function ErrorProbe({ error, action }: { error: unknown; action: ChatAction }) {
  const t = useTranslations("Chat.errors");
  return <p>{chatErrorMessage(error, action, t)}</p>;
}

function messageFor(error: unknown, action: ChatAction = "sendMessage", locale: Locale = "en") {
  const { unmount } = renderWithIntl(<ErrorProbe error={error} action={action} />, { locale });
  const text = screen.getByRole("paragraph").textContent ?? "";
  unmount();
  return text;
}

describe("chatErrorMessage", () => {
  it.each([
    [
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "raw" }),
      "The API could not be reached. Check your connection and try again.",
    ],
    [
      new ApiError({ status: 403, code: "csrf_failed", message: "raw" }),
      "Your session could not be confirmed. Reload the page and try again.",
    ],
    [
      new ApiError({ status: 401, code: "not_authenticated", message: "raw" }),
      "Your session has ended. Sign in again to continue.",
    ],
    [
      new ApiError({ status: 401, code: "token_expired", message: "raw" }),
      "Your session has ended. Sign in again to continue.",
    ],
    [
      new ApiError({ status: 401, code: "invalid_token", message: "raw" }),
      "Your session has ended. Sign in again to continue.",
    ],
    [
      new ApiError({ status: 404, code: "workspace_not_found", message: "raw" }),
      "This workspace no longer exists.",
    ],
    [
      new ApiError({ status: 404, code: "document_not_found", message: "raw" }),
      "One of the selected documents no longer exists. Refresh the list and try again.",
    ],
    [
      new ApiError({ status: 404, code: "chat_session_not_found", message: "raw" }),
      "This chat no longer exists.",
    ],
    [
      new ApiError({ status: 409, code: "chat_session_limit_reached", message: "raw" }),
      "This chat has reached its message limit. Start a new chat to continue.",
    ],
    [
      new ApiError({ status: 422, code: "validation_error", message: "raw" }),
      "Check your input and try again.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 1 }),
      "Too many messages. Try again in 1 second.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 25 }),
      "Too many messages. Try again in 25 seconds.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 61 }),
      "Too many messages. Try again in 2 minutes.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw" }),
      "Too many messages. Try again in a moment.",
    ],
    [
      new ApiError({
        status: 503,
        code: "chat_unavailable",
        message: "raw",
        retryAfterSeconds: 30,
      }),
      "The AI chat service is temporarily unavailable. Try again in 30 seconds.",
    ],
    [
      new ApiError({
        status: 503,
        code: "chat_unavailable",
        message: "raw",
        retryAfterSeconds: 120,
      }),
      "The AI chat service is temporarily unavailable. Try again in 2 minutes.",
    ],
    [
      new ApiError({ status: 503, code: "chat_unavailable", message: "raw" }),
      "The AI chat service is temporarily unavailable. Try again later.",
    ],
    [
      new ApiError({ status: 503, code: "chat_quota_exceeded", message: "raw" }),
      "The AI service has reached its usage limit.",
    ],
  ])("maps API error %j in English without leaking error.message", (error, expected) => {
    expect(messageFor(error)).toBe(expected);
  });

  it.each([
    ["loadSessions", "Your chats could not be loaded."],
    ["loadMoreSessions", "More chats could not be loaded."],
    ["createSession", "The chat could not be started. Try again."],
    ["openSession", "This chat could not be loaded."],
    ["updateSession", "Your changes could not be saved. Try again."],
    ["deleteSession", "The chat could not be deleted. Try again."],
    ["sendMessage", "Your message could not be sent. Try again."],
  ] as const)("falls back per action for %s", (action, expected) => {
    const unknown = new ApiError({ status: 500, code: "internal_error", message: "Server boom" });
    expect(messageFor(unknown, action)).toBe(expected);
    expect(messageFor(new Error("boom"), action)).toBe(expected);
  });

  it.each([
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 1 }),
      "Слишком много сообщений. Повторите через 1 секунду.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 2 }),
      "Слишком много сообщений. Повторите через 2 секунды.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 5 }),
      "Слишком много сообщений. Повторите через 5 секунд.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 60 }),
      "Слишком много сообщений. Повторите через 1 минуту.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 120 }),
      "Слишком много сообщений. Повторите через 2 минуты.",
    ],
    [
      new ApiError({ status: 429, code: "rate_limited", message: "raw", retryAfterSeconds: 300 }),
      "Слишком много сообщений. Повторите через 5 минут.",
    ],
    [
      new ApiError({
        status: 503,
        code: "chat_unavailable",
        message: "raw",
        retryAfterSeconds: 21,
      }),
      "Сервис ИИ-чата временно недоступен. Повторите через 21 секунду.",
    ],
    [
      new ApiError({ status: 503, code: "chat_unavailable", message: "raw" }),
      "Сервис ИИ-чата временно недоступен. Попробуйте позже.",
    ],
    [
      new ApiError({ status: 503, code: "chat_quota_exceeded", message: "raw" }),
      "Сервис ИИ исчерпал лимит использования.",
    ],
    [
      new ApiError({ status: 409, code: "chat_session_limit_reached", message: "raw" }),
      "В этом чате достигнут лимит сообщений. Начните новый чат, чтобы продолжить.",
    ],
  ])("formats Russian errors and plurals for %j", (error, expected) => {
    expect(messageFor(error, "sendMessage", "ru")).toBe(expected);
  });
});
