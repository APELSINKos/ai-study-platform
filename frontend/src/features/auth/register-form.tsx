"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, type ApiErrorDetail } from "@/lib/api/errors";
import type { RegisterRequest } from "@/lib/api/types";

import { authErrorMessage } from "./error-message";
import { useRegister } from "./hooks";
import { registerSchema, type RegisterFormValues } from "./schemas";
import { safeNext } from "./safe-next";

const FIELD_BY_SERVER_NAME: Record<string, keyof RegisterFormValues> = {
  email: "email",
  password: "password",
  display_name: "displayName",
};

function fieldNameFor(detail: ApiErrorDetail): keyof RegisterFormValues | null {
  return detail.field ? (FIELD_BY_SERVER_NAME[detail.field] ?? null) : null;
}

function toRegisterRequest(values: RegisterFormValues): RegisterRequest {
  return { email: values.email, password: values.password, display_name: values.displayName };
}

export function RegisterForm({ next }: { next?: string }) {
  const t = useTranslations("Auth");
  const tErrors = useTranslations("AuthErrors");
  const router = useRouter();
  const registerUser = useRegister();
  const [formError, setFormError] = useState<string | null>(null);
  const schema = useMemo(() => registerSchema(t), [t]);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<RegisterFormValues>({ resolver: zodResolver(schema) });

  const redirectTo = safeNext(next);
  const loginHref = redirectTo ? `/login?next=${encodeURIComponent(redirectTo)}` : "/login";

  function onSubmit(values: RegisterFormValues) {
    if (registerUser.isPending) {
      return;
    }
    setFormError(null);
    registerUser.mutate(toRegisterRequest(values), {
      onSuccess: () => router.replace(redirectTo ?? "/dashboard"),
      onError: (error) => {
        if (error instanceof ApiError && error.code === "email_taken") {
          setError("email", { message: authErrorMessage(error, tErrors) });
          return;
        }
        if (error instanceof ApiError && error.code === "validation_error") {
          const fieldErrors = error.details
            .map((detail) => ({ field: fieldNameFor(detail), message: detail.message }))
            .filter((entry): entry is { field: keyof RegisterFormValues; message: string } =>
              Boolean(entry.field),
            );
          if (fieldErrors.length > 0) {
            for (const { field, message } of fieldErrors) {
              setError(field, { message });
            }
            return;
          }
        }
        setFormError(authErrorMessage(error, tErrors));
      },
    });
  }

  return (
    <>
      <div className="index-card w-full max-w-md">
        <div className="px-5 pt-5 pb-4 sm:px-6 sm:pt-6">
          <h1 className="font-display text-title font-semibold">{t("register.title")}</h1>
        </div>
        <form
          onSubmit={handleSubmit(onSubmit)}
          noValidate
          className="flex flex-col gap-4 px-5 pb-6 sm:px-6"
        >
          <Field label={t("fields.name")} error={errors.displayName?.message}>
            <Input type="text" autoComplete="name" {...register("displayName")} />
          </Field>
          <Field label={t("fields.email")} error={errors.email?.message}>
            <Input type="email" autoComplete="email" {...register("email")} />
          </Field>
          <Field label={t("fields.password")} error={errors.password?.message}>
            <Input type="password" autoComplete="new-password" {...register("password")} />
          </Field>
          {formError ? (
            <p role="alert" className="text-margin text-sm">
              {formError}
            </p>
          ) : null}
          <Button type="submit" variant="primary" isLoading={registerUser.isPending}>
            {t("register.submit")}
          </Button>
        </form>
      </div>
      <p className="text-ink-soft mt-6 text-sm">
        {t("register.switchPrompt")}{" "}
        <Button asChild variant="link">
          <Link href={loginHref}>{t("register.switchLink")}</Link>
        </Button>
      </p>
    </>
  );
}
