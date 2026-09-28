import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/** The small numbered pen mark that ties a claim in an answer to its source. */
export function CitationMark({
  number,
  className,
  ...props
}: ComponentProps<"span"> & { number: number }) {
  return (
    <span
      className={cn(
        "bg-pen text-on-pen inline-flex size-5 items-center justify-center rounded-full text-[0.6875rem] leading-none font-semibold tabular-nums",
        className,
      )}
      {...props}
    >
      {number}
    </span>
  );
}
