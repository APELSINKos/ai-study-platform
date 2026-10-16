import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { WorkspaceView } from "@/features/workspaces/workspace-view";

// A static title: the server never sees the session, so it cannot know the workspace's name.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Workspaces.detail");
  return { title: t("metaTitle") };
}

export default async function WorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WorkspaceView id={id} />;
}
