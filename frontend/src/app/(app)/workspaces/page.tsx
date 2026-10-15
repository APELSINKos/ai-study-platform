import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { WorkspaceList } from "@/features/workspaces/workspace-list";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Workspaces");
  return { title: t("metaTitle") };
}

export default function WorkspacesPage() {
  return <WorkspaceList />;
}
