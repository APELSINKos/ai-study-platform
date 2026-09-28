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

import { authErrorMessage } from "./error-message";
import { useLogin } from "./hooks";
import { loginSchema, type LoginFormValues } from "./schemas";
import { safeNext } from "./safe-next";

const FIELD_BY_SERVER_NAME: Record<string, keyof LoginFormValues> = {
  email: "email",
  password: "password",
};

function fieldNameFor(detail: ApiErrorDetail): keyof LoginFormValues | null {
  return detail.field ? (FIELD_BY_SERVER_NAME[detail.field] ?? null) : null;
}

export function LoginForm({ next }: { next?: string }) {
  const t = useTranslations("Auth");
  const tErrors = useTranslations("AuthErrors");
  const router = useRouter();
  const login = useLogin();
  const [formError, setFormError] = useState<string | null>(null);
  const schema = useMemo(() => loginSchema(t), [t]);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<LoginFormValues>({ resolver: zodResolver(schema) });

  const redirectTo = safeNext(next);
  const registerHref = redirectTo
    ? `/register?next=${encodeURIComponent(redirectTo)}`
    : "/register";

  function onSubmit(values: LoginFormValues) {
    if (login.isPending) {
      return;
    }
    setFormError(null);
    login.mutate(values, {
      onSuccess: () => router.replace(redirectTo ?? "/dashboard"),
      onError: (error) => {
        if (error instanceof ApiError && error.code === "validation_error") {
          const fieldErrors = error.details
            .map((detail) => ({ field: fieldNameFor(detail), message: detail.message }))
            .filter((entry): entry is { field: keyof LoginFormValues; message: string } =>
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
          <h1 className="font-display text-title font-semibold">{t("login.title")}</h1>
        </div>
        <form
          onSubmit={handleSubmit(onSubmit)}
          noValidate
          className="flex flex-col gap-4 px-5 pb-6 sm:px-6"
        >
          <Field label={t("fields.email")} error={errors.email?.message}>
            <Input type="email" autoComplete="email" {...register("email")} />
          </Field>
          <Field label={t("fields.password")} error={errors.password?.message}>
            <Input type="password" autoComplete="current-password" {...register("password")} />
          </Field>
          {formError ? (
            <p role="alert" className="text-margin text-sm">
              {formError}
            </p>
          ) : null}
          <Button type="submit" variant="primary" isLoading={login.isPending}>
            {t("login.submit")}
          </Button>
        </form>
      </div>
      <p className="text-ink-soft mt-6 text-sm">
        {t("login.switchPrompt")}{" "}
        <Button asChild variant="link">
          <Link href={registerHref}>{t("login.switchLink")}</Link>
        </Button>
      </p>
    </>
  );
}
