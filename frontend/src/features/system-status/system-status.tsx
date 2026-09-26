"use client";

import { CircleNotchIcon } from "@phosphor-icons/react/ssr";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import type { ReadinessResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { readinessFromError } from "./readiness";
import { useReadiness } from "./use-readiness";

type Summary = "loading" | "ok" | "degraded" | "unreachable";
type Check = ReadinessResponse["checks"][string];

const KNOWN_COMPONENTS = ["database", "redis"] as const;
type KnownComponent = (typeof KNOWN_COMPONENTS)[number];
const SKELETON_ROWS = KNOWN_COMPONENTS.length;
// One line of the index card: every line has the same height and a pale rule above it.
const RULED_LINE = "border-t border-rule px-4 py-3 text-sm sm:px-5";

function isKnownComponent(name: string): name is KnownComponent {
  return (KNOWN_COMPONENTS as readonly string[]).includes(name);
}

export function SystemStatus({ className }: { className?: string }) {
  const t = useTranslations("Status");
  const { data, error, isError, isPending, refetch } = useReadiness();
  // Only a check the user asked for shows a spinner; the background poll stays silent.
  const [isRechecking, setIsRechecking] = useState(false);
  // A failed check wins over data from an earlier success, which the query keeps.
  const readiness = isError ? readinessFromError(error) : (data ?? null);
  const summary: Summary = isPending
    ? "loading"
    : readiness === null
      ? "unreachable"
      : readiness.status === "ok"
        ? "ok"
        : "degraded";

  function recheck() {
    if (isRechecking) {
      return;
    }
    setIsRechecking(true);
    void refetch().finally(() => setIsRechecking(false));
  }

  return (
    <section
      aria-labelledby="system-status-title"
      aria-busy={isPending || undefined}
      className={cn("index-card w-full max-w-xl", className)}
    >
      <div className="flex items-center justify-between gap-4 px-4 pt-4 pb-3 sm:px-5">
        <h2 id="system-status-title" className="font-display text-lg font-semibold">
          {t("title")}
        </h2>
        {/*
          Not `isLoading`: that disables the button, and a disabled button drops keyboard focus
          to the page body. The negative margin lines the label up with the latency column.
        */}
        <Button
          variant="ghost"
          size="sm"
          className="-mr-3"
          aria-busy={isRechecking || undefined}
          onClick={recheck}
        >
          {isRechecking ? <CircleNotchIcon aria-hidden className="animate-spin" /> : null}
          {t("refresh")}
        </Button>
      </div>
      <p role="status" className="px-4 py-3 text-sm sm:px-5">
        {t(`summary.${summary}`)}
      </p>
      {readiness ? (
        <ComponentRows checks={readiness.checks} />
      ) : isPending ? (
        <SkeletonRows />
      ) : (
        <RequestIdNote error={error} />
      )}
    </section>
  );
}

function ComponentRows({ checks }: { checks: ReadinessResponse["checks"] }) {
  const t = useTranslations("Status");
  return (
    <dl>
      {Object.entries(checks).map(([name, check]) => (
        <div key={name} className={cn(RULED_LINE, "flex items-center justify-between gap-4")}>
          <dt>{isKnownComponent(name) ? t(`components.${name}`) : name}</dt>
          <dd className="flex items-center gap-3">
            <StateLabel check={check} />
            {check.latency_ms != null ? (
              <span className="text-ink-soft min-w-14 text-right tabular-nums">
                {t("latency", { ms: check.latency_ms })}
              </span>
            ) : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function StateLabel({ check }: { check: Check }) {
  const t = useTranslations("Status");
  const ok = check.status === "ok";
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden className={cn("size-2 rounded-full", ok ? "bg-ok" : "bg-margin")} />
      {t(ok ? "state.ok" : "state.error")}
    </span>
  );
}

function SkeletonRows() {
  return (
    <div aria-hidden>
      {Array.from({ length: SKELETON_ROWS }, (_, index) => (
        <div key={index} className={RULED_LINE}>
          <div className="rounded-control bg-paper h-5 w-2/3 animate-pulse" />
        </div>
      ))}
    </div>
  );
}

function RequestIdNote({ error }: { error: unknown }) {
  const t = useTranslations("Status");
  const requestId = error instanceof ApiError ? error.requestId : null;
  if (!requestId) {
    return null;
  }
  return (
    <p className={cn(RULED_LINE, "text-ink-soft text-xs")}>{t("requestId", { id: requestId })}</p>
  );
}
