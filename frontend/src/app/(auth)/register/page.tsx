import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { RegisterForm } from "@/features/auth/register-form";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Auth.register");
  return { title: t("metaTitle") };
}

export default async function RegisterPage({ searchParams }: { searchParams: SearchParams }) {
  const { next } = await searchParams;
  return <RegisterForm next={Array.isArray(next) ? next[0] : next} />;
}
