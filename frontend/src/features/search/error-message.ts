import type { useTranslations } from "next-intl";

import { waitOf } from "@/features/documents/error-message";
import { WORKSPACE_NOT_FOUND_CODE } from "@/features/workspaces/error-message";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";

type SearchErrorsTranslator = ReturnType<typeof useTranslations<"Search.errors">>;

function rateLimitedMessage(t: SearchErrorsTranslator, retryAfterSeconds: number | null): string {
  const wait = waitOf(retryAfterSeconds);
  if (wait === null) {
    return t("rateLimitedGeneric");
  }
  return "minutes" in wait ? t("rateLimitedMinutes", wait) : t("rateLimited", wait);
}

/** A translated sentence for a failed search; the backend's English never shows. */
export function searchErrorMessage(error: unknown, t: SearchErrorsTranslator): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case NETWORK_ERROR_CODE:
        return t("networkError");
      case "not_authenticated":
      case "token_expired":
      case "invalid_token":
        return t("sessionExpired");
      case WORKSPACE_NOT_FOUND_CODE:
        return t("workspaceNotFound");
      // The query is too long or holds a character the API refuses, as an edited address can.
      case "validation_error":
        return t("invalidQuery");
      case "rate_limited":
        return rateLimitedMessage(t, error.retryAfterSeconds);
    }
  }
  // search_unavailable lands here too: only a search by embeddings alone gets it, and the page
  // never asks for one.
  return t("failed");
}
