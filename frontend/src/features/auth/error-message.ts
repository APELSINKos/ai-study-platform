import type { useTranslations } from "next-intl";

import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";

type AuthErrorsTranslator = ReturnType<typeof useTranslations<"AuthErrors">>;

const SECONDS_PER_MINUTE = 60;

function rateLimitedMessage(t: AuthErrorsTranslator, retryAfterSeconds: number | null): string {
  if (retryAfterSeconds === null) {
    return t("rateLimitedGeneric");
  }
  if (retryAfterSeconds >= SECONDS_PER_MINUTE) {
    const minutes = Math.ceil(retryAfterSeconds / SECONDS_PER_MINUTE);
    return t("rateLimitedMinutes", { minutes });
  }
  return t("rateLimited", { seconds: retryAfterSeconds });
}

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
      return rateLimitedMessage(t, error.retryAfterSeconds);
    case "validation_error":
      return t("validationError");
    case NETWORK_ERROR_CODE:
      return t("networkError");
    default:
      return t("fallback");
  }
}
