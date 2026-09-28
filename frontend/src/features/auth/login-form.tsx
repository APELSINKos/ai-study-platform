"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { IndexCard, IndexCardBody, IndexCardHeader } from "@/components/ui/index-card";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";

import { authErrorMessage } from "./error-message";
import { useLogin } from "./hooks";
import { loginSchema, type LoginFormValues } from "./schemas";
import { safeNext } from "./safe-next";
import { matchServerFields } from "./server-fields";

const FIELD_BY_SERVER_NAME: Record<string, keyof LoginFormValues> = {
  email: "email",
  password: "password",
};

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
          // The backend's own wording is English-only, so fields get messages from the catalog.
          const { fields, hasUnmatched } = matchServerFields(error.details, FIELD_BY_SERVER_NAME);
          for (const [index, field] of fields.entries()) {
            setError(
              field,
              {
                message:
                  field === "email" ? t("validation.emailInvalid") : t("validation.fieldRejected"),
              },
              { shouldFocus: index === 0 },
            );
          }
          if (fields.length > 0 && !hasUnmatched) {
            return;
          }
        }
        setFormError(authErrorMessage(error, tErrors));
      },
    });
  }

  return (
    <>
      <IndexCard className="w-full max-w-md">
        <IndexCardHeader>
          <h1 className="font-display text-title font-semibold">{t("login.title")}</h1>
        </IndexCardHeader>
        <IndexCardBody
          as="form"
          onSubmit={handleSubmit(onSubmit)}
          noValidate
          className="flex flex-col gap-4"
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
        </IndexCardBody>
      </IndexCard>
      <p className="text-ink-soft mt-6 text-sm">
        {t("login.switchPrompt")}{" "}
        <Button asChild variant="link">
          <Link href={registerHref}>{t("login.switchLink")}</Link>
        </Button>
      </p>
    </>
  );
}
