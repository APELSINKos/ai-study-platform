"use client";

import { useFormatter } from "next-intl";
import { useSyncExternalStore } from "react";

// Reserves the line's height before the client-formatted date replaces it, so
// nothing shifts once it appears.
const RESERVED_LINE = " ";

const subscribeToNothing = () => () => {};

// The date is only safe to format once we're in the browser: the server and
// the browser's time zone can disagree, which would make the date itself a
// hydration mismatch.
function useIsClient(): boolean {
  return useSyncExternalStore(
    subscribeToNothing,
    () => true,
    () => false,
  );
}

export function DashboardMarginDate() {
  const format = useFormatter();
  const isClient = useIsClient();

  return (
    <p className="margin-note">
      {isClient
        ? format.dateTime(new Date(), { weekday: "long", day: "numeric", month: "long" })
        : RESERVED_LINE}
    </p>
  );
}
