import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tailwind-merge must know the custom theme scales, otherwise it mistakes `text-display` for a colour.
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ["display", "headline", "title"],
      radius: ["control", "panel"],
      ease: ["out-soft"],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
