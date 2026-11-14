import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { searchQueryFrom } from "@/features/search/query-param";
import { WorkspaceView } from "@/features/workspaces/workspace-view";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

// A static title: the server never sees the session, so it cannot know the workspace's name.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Workspaces.detail");
  return { title: t("metaTitle") };
}

/** `?q=` holds a search of the workspace, so Back and Forward step through earlier searches. */
export default async function WorkspacePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
}) {
  const { id } = await params;
  const { q } = await searchParams;
  return <WorkspaceView id={id} query={searchQueryFrom(q)} />;
}
