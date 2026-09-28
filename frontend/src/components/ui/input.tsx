import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Input({ className, ref, ...props }: ComponentProps<"input">) {
  return (
    <input
      ref={ref}
      className={cn(
        "border-rule-strong bg-sheet text-ink placeholder:text-ink-soft rounded-control h-10 w-full border px-3 text-sm",
        "focus-visible:outline-pen focus-visible:outline-2 focus-visible:outline-offset-2",
        "aria-invalid:border-margin",
        "disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
