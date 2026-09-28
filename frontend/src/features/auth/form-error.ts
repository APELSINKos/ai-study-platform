import type { useTranslations } from "next-intl";

import { ApiError } from "@/lib/api/errors";

import { authErrorMessage } from "./error-message";
import { matchServerFields } from "./server-fields";

type AuthTranslator = ReturnType<typeof useTranslations<"Auth">>;
type AuthErrorsTranslator = ReturnType<typeof useTranslations<"Auth.errors">>;

type SetFieldError<Field extends string> = (
  field: Field,
  error: { message: string },
  options: { shouldFocus: boolean },
) => void;

interface HandleAuthFormErrorOptions<Field extends string> {
  error: unknown;
  fieldByServerName: Readonly<Record<string, Field>>;
  /** Set for the register form only: an email_taken failure names this field directly. */
  emailTakenField?: Field;
  t: AuthTranslator;
  tErrors: AuthErrorsTranslator;
  setError: SetFieldError<Field>;
  setFormError: (message: string) => void;
}

/**
 * Shared onError handling for the login and register forms: a server-named field gets its
 * own message and focus, otherwise the failure becomes the form-level alert.
 */
export function handleAuthFormError<Field extends string>({
  error,
  fieldByServerName,
  emailTakenField,
  t,
  tErrors,
  setError,
  setFormError,
}: HandleAuthFormErrorOptions<Field>): void {
  if (emailTakenField && error instanceof ApiError && error.code === "email_taken") {
    setError(emailTakenField, { message: authErrorMessage(error, tErrors) }, { shouldFocus: true });
    return;
  }
  if (error instanceof ApiError && error.code === "validation_error") {
    // The backend's own wording is English-only, so fields get messages from the catalog.
    const { fields, hasUnmatched } = matchServerFields(error.details, fieldByServerName);
    for (const [index, field] of fields.entries()) {
      setError(
        field,
        {
          message: field === "email" ? t("validation.emailInvalid") : t("validation.fieldRejected"),
        },
        { shouldFocus: index === 0 },
      );
    }
    if (fields.length > 0 && !hasUnmatched) {
      return;
    }
  }
  setFormError(authErrorMessage(error, tErrors));
}
