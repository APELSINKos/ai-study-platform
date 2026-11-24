import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ChatView } from "@/features/chat/chat-view";
import { sessionParamFrom, workspaceParamFrom } from "@/features/chat/url-params";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Chat");
  return { title: t("metaTitle") };
}

/**
 * `/chat` shows the session index and new-chat creator; `?session=<id>` opens one conversation,
 * and `?workspace=<id>` pre-selects a workspace for a new chat.
 */
export default async function ChatPage({ searchParams }: { searchParams: SearchParams }) {
  const { session, workspace } = await searchParams;
  return (
    <ChatView
      sessionParam={sessionParamFrom(session)}
      initialWorkspaceId={workspaceParamFrom(workspace)}
    />
  );
}
