import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import type { WorkspaceOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { ExamCountdown } from "./exam-countdown";

/** One ruled line of a workspace list. The name is the link, stretched over the whole line. */
export function WorkspaceRow({ workspace }: { workspace: WorkspaceOut }) {
  const t = useTranslations("Workspaces.row");
  const { stats } = workspace;

  return (
    <li className="hover:bg-paper relative flex flex-col gap-3 px-5 py-4 transition-colors sm:flex-row sm:items-baseline sm:justify-between sm:gap-8 sm:px-6">
      <div className="min-w-0">
        <Link
          href={`/workspaces/${workspace.id}`}
          className="font-display text-ink focus-visible:after:outline-pen text-lg font-semibold break-words after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-solid"
        >
          {workspace.name}
        </Link>
        {workspace.description ? (
          <p className="text-ink-soft mt-1 line-clamp-2 text-sm break-words">
            {workspace.description}
          </p>
        ) : null}
        <p className="text-ink-soft mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <span>{t("documents", { count: stats.document_count })}</span>
          {stats.processing_count > 0 ? (
            <Tally dotClassName="bg-pen">
              {t("processing", { count: stats.processing_count })}
            </Tally>
          ) : null}
          {stats.failed_count > 0 ? (
            <Tally dotClassName="bg-margin">{t("failed", { count: stats.failed_count })}</Tally>
          ) : null}
        </p>
      </div>
      {/* One line under the counts on a phone, a column of its own beside them on wider screens. */}
      {workspace.exam_date ? (
        <ExamCountdown
          examDate={workspace.exam_date}
          className="flex-row flex-wrap gap-x-3 sm:shrink-0 sm:flex-col sm:items-end"
        />
      ) : null}
    </li>
  );
}

/** A count marked by a status-coloured dot; the colour never goes on the words. */
function Tally({ dotClassName, children }: { dotClassName: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", dotClassName)} />
      {children}
    </span>
  );
}
