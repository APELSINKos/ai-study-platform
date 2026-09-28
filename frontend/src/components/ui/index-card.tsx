import type { ComponentProps, ComponentPropsWithoutRef, ElementType } from "react";

import { cn } from "@/lib/utils";

/** The notebook index card: a bordered, raised sheet used for forms and panels. */
export function IndexCard({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("index-card", className)} {...props} />;
}

/** The card's title row, underlined by the red rule. */
export function IndexCardHeader({ className, ...props }: ComponentProps<"div">) {
  return (
    <div className={cn("index-card-header px-5 pt-5 pb-4 sm:px-6 sm:pt-6", className)} {...props} />
  );
}

type IndexCardBodyProps<E extends ElementType> = { as?: E } & Omit<
  ComponentPropsWithoutRef<E>,
  "as"
>;

/** The card's main content, below the header. Renders as a `form` when the body is one. */
export function IndexCardBody<E extends ElementType = "div">({
  as,
  className,
  ...props
}: IndexCardBodyProps<E>) {
  const Component = as ?? "div";
  return <Component className={cn("px-5 pt-5 pb-6 sm:px-6 sm:pt-6", className)} {...props} />;
}
