import { CircleNotchIcon } from "@phosphor-icons/react/ssr";
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps, MouseEvent } from "react";

import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  [
    "inline-flex shrink-0 items-center justify-center gap-2 rounded-control font-medium whitespace-nowrap select-none",
    "transition-[background-color,border-color,color,transform] duration-150 ease-out-soft active:translate-y-px",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-pen",
    "disabled:pointer-events-none disabled:opacity-50 aria-busy:cursor-progress",
    "[&_svg]:size-4 [&_svg]:shrink-0",
  ],
  {
    variants: {
      variant: {
        primary: "bg-pen text-on-pen shadow-[inset_0_-2px_0_rgb(0_0_0/0.22)] hover:bg-pen-hover",
        secondary:
          "border border-rule-strong bg-sheet text-ink hover:border-ink-soft/50 hover:bg-paper",
        ghost: "text-ink-soft hover:bg-ink/5 hover:text-ink",
        danger: "border border-margin/50 text-margin hover:bg-margin hover:text-sheet",
        link: "text-pen underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-sm",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "size-10",
      },
    },
    compoundVariants: [{ variant: "link", className: "h-auto px-0" }],
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    isLoading?: boolean;
  };

export function Button({
  className,
  variant,
  size,
  asChild = false,
  isLoading = false,
  disabled,
  type = "button",
  onClick,
  children,
  ...props
}: ButtonProps) {
  const classes = cn(buttonVariants({ variant, size }), className);
  const dataVariant = variant ?? "secondary";

  // Loading must not set native `disabled`: a disabled button drops keyboard focus to the page
  // body, which is disorienting right after the user triggered the action. Blocking the click
  // in the handler achieves the same "no double submit" guarantee without that side effect.
  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (isLoading) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  }

  if (asChild) {
    return (
      <Slot.Root data-variant={dataVariant} className={classes} onClick={onClick} {...props}>
        {children}
      </Slot.Root>
    );
  }

  return (
    <button
      type={type}
      data-variant={dataVariant}
      data-loading={isLoading || undefined}
      className={classes}
      disabled={disabled}
      aria-disabled={isLoading || undefined}
      aria-busy={isLoading || undefined}
      onClick={handleClick}
      {...props}
    >
      {isLoading ? <CircleNotchIcon aria-hidden className="animate-spin" /> : null}
      {children}
    </button>
  );
}
