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

import { DASHBOARD_PATH } from "./constants";
import { handleAuthFormError } from "./form-error";
import { useLogin } from "./hooks";
import { loginSchema, type LoginFormValues } from "./schemas";
import { safeNext } from "./safe-next";

const FIELD_BY_SERVER_NAME: Record<string, keyof LoginFormValues> = {
  email: "email",
  password: "password",
};

export function LoginForm({ next }: { next?: string }) {
  const t = useTranslations("Auth");
  const tErrors = useTranslations("Auth.errors");
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
      onSuccess: () => router.replace(redirectTo ?? DASHBOARD_PATH),
      onError: (error) =>
        handleAuthFormError({
          error,
          fieldByServerName: FIELD_BY_SERVER_NAME,
          t,
          tErrors,
          setError,
          setFormError,
        }),
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
