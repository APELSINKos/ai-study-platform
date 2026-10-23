import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * A quiet note under a heading whose feature Recall does not have yet. The ring is drawn in
 * dashes, like a station on a line that has not been reached.
 */
export function ComingNext({ className }: { className?: string }) {
  const t = useTranslations("Landing");

  return (
    <p
      className={cn(
        "font-display text-ink-soft flex items-center gap-2 text-[0.9375rem] italic",
        className,
      )}
    >
      <svg aria-hidden viewBox="0 0 12 12" className="size-3 flex-none overflow-visible">
        <circle
          cx="6"
          cy="6"
          r="4.75"
          fill="none"
          strokeWidth={1.25}
          strokeDasharray="2.2 1.8"
          className="stroke-pen"
        />
      </svg>
      {t("comingNext")}
    </p>
  );
}
