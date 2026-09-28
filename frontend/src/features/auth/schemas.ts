import type { useTranslations } from "next-intl";
import { z } from "zod";

export const PASSWORD_MIN_LENGTH = 10;
export const PASSWORD_MAX_LENGTH = 128;
export const DISPLAY_NAME_MAX_LENGTH = 80;

type AuthTranslator = ReturnType<typeof useTranslations<"Auth">>;

export interface LoginFormValues {
  email: string;
  password: string;
}

export interface RegisterFormValues {
  email: string;
  password: string;
  displayName: string;
}

function emailField(t: AuthTranslator) {
  return z.string().min(1, t("validation.emailRequired")).email(t("validation.emailInvalid"));
}

export function loginSchema(t: AuthTranslator) {
  return z.object({
    email: emailField(t),
    password: z
      .string()
      .min(1, t("validation.passwordRequired"))
      .max(PASSWORD_MAX_LENGTH, t("validation.passwordTooLong", { max: PASSWORD_MAX_LENGTH })),
  });
}

export function registerSchema(t: AuthTranslator) {
  return z.object({
    email: emailField(t),
    password: z
      .string()
      .min(PASSWORD_MIN_LENGTH, t("validation.passwordTooShort", { min: PASSWORD_MIN_LENGTH }))
      .max(PASSWORD_MAX_LENGTH, t("validation.passwordTooLong", { max: PASSWORD_MAX_LENGTH })),
    displayName: z
      .string()
      .trim()
      .min(1, t("validation.nameRequired"))
      .max(DISPLAY_NAME_MAX_LENGTH, t("validation.nameTooLong", { max: DISPLAY_NAME_MAX_LENGTH })),
  });
}
