import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { WorkspaceList } from "@/features/workspaces/workspace-list";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

/** `?new=1` opens the create form, for links whose whole point is a new workspace. */
const OPEN_FORM_VALUE = "1";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Workspaces");
  return { title: t("metaTitle") };
}

export default async function WorkspacesPage({ searchParams }: { searchParams: SearchParams }) {
  const { new: openForm } = await searchParams;
  return <WorkspaceList startWithForm={openForm === OPEN_FORM_VALUE} />;
}
