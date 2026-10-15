"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { IndexCard, IndexCardBody, IndexCardHeader } from "@/components/ui/index-card";
import { workspaceErrorMessage } from "@/features/workspaces/error-message";
import { useRecentWorkspaces } from "@/features/workspaces/hooks";
import { WorkspaceRow } from "@/features/workspaces/workspace-row";
import { cn } from "@/lib/utils";

// The workspaces page opens its create form for this link (see app/(app)/workspaces/page.tsx).
const NEW_WORKSPACE_HREF = "/workspaces?new=1";
const SKELETON_ROWS = 2;

/** The dashboard's way into the workspaces: the latest few, or the invitation to make one. */
export function RecentWorkspaces({ className }: { className?: string }) {
  const t = useTranslations("Dashboard.workspaces");
  const tWorkspaces = useTranslations("Workspaces");
  const tErrors = useTranslations("Workspaces.errors");
  const titleId = useId();
  const recent = useRecentWorkspaces();

  if (recent.isPending) {
    return (
      <IndexCard aria-busy="true" className={className}>
        <span className="sr-only">{tWorkspaces("list.loading")}</span>
        <div aria-hidden>
          <div className="index-card-header px-5 pt-5 pb-4 sm:px-6 sm:pt-6">
            <div className="bg-paper h-6 w-48 animate-pulse rounded" />
          </div>
          {Array.from({ length: SKELETON_ROWS }, (_, index) => (
            <div key={index} className="border-rule border-t px-5 py-4 first:border-t-0 sm:px-6">
              <div className="bg-paper h-5 w-1/2 animate-pulse rounded" />
              <div className="bg-paper mt-3 h-4 w-1/3 animate-pulse rounded" />
            </div>
          ))}
        </div>
      </IndexCard>
    );
  }

  if (recent.data === undefined) {
    return (
      <div className={cn("flex flex-col items-start gap-4", className)}>
        <p role="alert" className="text-ink-soft text-sm">
          {workspaceErrorMessage(recent.error, "load", tErrors)}
        </p>
        <Button
          variant="secondary"
          isLoading={recent.isFetching}
          onClick={() => void recent.refetch()}
        >
          {tWorkspaces("list.retry")}
        </Button>
      </div>
    );
  }

  const workspaces = recent.data.items;
  if (workspaces.length === 0) {
    return (
      <IndexCard className={className}>
        <IndexCardHeader>
          <h2 className="font-display text-lg font-semibold">{t("emptyTitle")}</h2>
        </IndexCardHeader>
        <IndexCardBody className="flex flex-col items-start gap-5">
          <p className="text-ink-soft max-w-[60ch] text-sm text-pretty">{t("emptyBody")}</p>
          <Button asChild variant="primary">
            <Link href={NEW_WORKSPACE_HREF}>{tWorkspaces("newWorkspace")}</Link>
          </Button>
        </IndexCardBody>
      </IndexCard>
    );
  }

  return (
    <section aria-labelledby={titleId} className={cn("index-card overflow-hidden", className)}>
      <IndexCardHeader>
        <h2 id={titleId} className="font-display text-lg font-semibold">
          {t("recentTitle")}
        </h2>
      </IndexCardHeader>
      <ul className="divide-rule divide-y">
        {workspaces.map((workspace) => (
          <WorkspaceRow key={workspace.id} workspace={workspace} />
        ))}
      </ul>
      <div className="border-rule border-t px-5 py-3 sm:px-6">
        <Button asChild variant="link">
          <Link href="/workspaces">{t("allLink")}</Link>
        </Button>
      </div>
    </section>
  );
}
