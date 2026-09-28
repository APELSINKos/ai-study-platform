import type { useTranslations } from "next-intl";

import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";

type AuthErrorsTranslator = ReturnType<typeof useTranslations<"AuthErrors">>;

/** Maps a request failure to a translated, user-facing message for the auth forms. */
export function authErrorMessage(error: unknown, t: AuthErrorsTranslator): string {
  if (!(error instanceof ApiError)) {
    return t("fallback");
  }
  switch (error.code) {
    case "email_taken":
      return t("emailTaken");
    case "invalid_credentials":
      return t("invalidCredentials");
    case "rate_limited":
      return error.retryAfterSeconds !== null
        ? t("rateLimited", { seconds: error.retryAfterSeconds })
        : t("rateLimitedGeneric");
    case "validation_error":
      return t("validationError");
    case NETWORK_ERROR_CODE:
      return t("networkError");
    default:
      return t("fallback");
  }
}
