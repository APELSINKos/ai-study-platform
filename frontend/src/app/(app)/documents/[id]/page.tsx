import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { DocumentView } from "@/features/documents/document-view";

// A static title: the server never sees the session, so it cannot know the document's title.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Documents.detail");
  return { title: t("metaTitle") };
}

export default async function DocumentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DocumentView id={id} />;
}
