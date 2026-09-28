import { HouseIcon, type Icon } from "@phosphor-icons/react";

export interface NavItem {
  href: string;
  labelKey: "dashboard";
  Icon: Icon;
}

/** Implemented destinations only; more are added here as the app grows. */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", labelKey: "dashboard", Icon: HouseIcon },
];
