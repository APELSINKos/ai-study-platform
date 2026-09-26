import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function SegmentedGroup({
  label,
  busy = false,
  children,
}: {
  label: string;
  busy?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      aria-busy={busy || undefined}
      className="rounded-control border-rule bg-sheet inline-flex items-center gap-0.5 border p-0.5"
    >
      {children}
    </div>
  );
}

export function SegmentedButton({
  pressed,
  className,
  ...props
}: ComponentProps<"button"> & { pressed: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={cn(
        "text-ink-soft hover:text-ink inline-flex h-7 min-w-7 items-center justify-center rounded-[calc(var(--radius-control)-2px)] px-2 text-xs font-medium transition-colors duration-150",
        pressed && "bg-ink text-sheet hover:text-sheet",
        className,
      )}
      {...props}
    />
  );
}
