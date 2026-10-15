import { FoldersIcon, HouseIcon, type Icon } from "@phosphor-icons/react";

export interface NavItem {
  href: string;
  labelKey: "dashboard" | "workspaces";
  Icon: Icon;
  /** The sections the destination stays marked in, with every path below them. */
  sections: readonly string[];
}

/** Implemented destinations only; more are added here as the app grows. */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", labelKey: "dashboard", Icon: HouseIcon, sections: ["/dashboard"] },
  {
    href: "/workspaces",
    labelKey: "workspaces",
    Icon: FoldersIcon,
    // A document is opened from its workspace, so its page belongs to the same section.
    sections: ["/workspaces", "/documents"],
  },
];

/** True on a section's own path or below it (`/workspaces/1`, not `/workspacesx`). */
export function isNavItemActive(item: NavItem, pathname: string): boolean {
  return item.sections.some(
    (section) => pathname === section || pathname.startsWith(`${section}/`),
  );
}
