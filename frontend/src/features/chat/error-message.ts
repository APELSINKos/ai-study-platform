import type { useTranslations } from "next-intl";

import { DOCUMENT_NOT_FOUND_CODE, waitOf } from "@/features/documents/error-message";
import { WORKSPACE_NOT_FOUND_CODE } from "@/features/workspaces/error-message";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";

type ChatErrorsTranslator = ReturnType<typeof useTranslations<"Chat.errors">>;

/** The answer for a chat session that does not exist or belongs to someone else. */
export const CHAT_SESSION_NOT_FOUND_CODE = "chat_session_not_found";

/** What the user was doing; it words the message when the failure has no wording of its own. */
export type ChatAction =
  | "loadSessions"
  | "loadMoreSessions"
  | "createSession"
  | "openSession"
  | "updateSession"
  | "deleteSession"
  | "sendMessage";

const FAILED_ACTION_KEYS = {
  loadSessions: "loadSessionsFailed",
  loadMoreSessions: "loadMoreSessionsFailed",
  createSession: "createFailed",
  openSession: "openFailed",
  updateSession: "updateFailed",
  deleteSession: "deleteFailed",
  sendMessage: "sendFailed",
} as const satisfies Record<ChatAction, string>;

function rateLimitedMessage(t: ChatErrorsTranslator, retryAfterSeconds: number | null): string {
  const wait = waitOf(retryAfterSeconds);
  if (wait === null) {
    return t("rateLimitedGeneric");
  }
  return "minutes" in wait ? t("rateLimitedMinutes", wait) : t("rateLimited", wait);
}

function unavailableMessage(t: ChatErrorsTranslator, retryAfterSeconds: number | null): string {
  const wait = waitOf(retryAfterSeconds);
  if (wait === null) {
    return t("unavailableGeneric");
  }
  return "minutes" in wait ? t("unavailableMinutes", wait) : t("unavailable", wait);
}

/** A translated sentence for a failed chat request; the backend's English never shows. */
export function chatErrorMessage(
  error: unknown,
  action: ChatAction,
  t: ChatErrorsTranslator,
): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case NETWORK_ERROR_CODE:
        return t("networkError");
      case "csrf_failed":
        return t("csrfFailed");
      case "not_authenticated":
      case "token_expired":
      case "invalid_token":
        return t("sessionExpired");
      case WORKSPACE_NOT_FOUND_CODE:
        return t("workspaceNotFound");
      case DOCUMENT_NOT_FOUND_CODE:
        return t("documentNotFound");
      case CHAT_SESSION_NOT_FOUND_CODE:
        return t("sessionNotFound");
      case "chat_session_limit_reached":
        return t("sessionLimitReached");
      case "validation_error":
        return t("validationError");
      case "rate_limited":
        return rateLimitedMessage(t, error.retryAfterSeconds);
      case "chat_unavailable":
        return unavailableMessage(t, error.retryAfterSeconds);
      case "chat_quota_exceeded":
        return t("quotaExceeded");
    }
  }
  return t(FAILED_ACTION_KEYS[action]);
}
