import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { DocumentView } from "@/features/documents/document-view";
import { fragmentFrom } from "@/features/documents/fragment-param";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

// A static title: the server never sees the session, so it cannot know the document's title.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Documents.detail");
  return { title: t("metaTitle") };
}

/** `?fragment=` opens the document at one of its passages, the way a search result links to it. */
export default async function DocumentDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
}) {
  const { id } = await params;
  const { fragment } = await searchParams;
  return <DocumentView id={id} fragment={fragmentFrom(fragment)} />;
}
