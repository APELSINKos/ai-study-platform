import { DASHBOARD_PATH, LOGIN_PATH, loginRedirectUrl } from "./constants";
import { isProtectedPath } from "./protected-paths";

const AUTH_PATHS = new Set<string>([LOGIN_PATH, "/register"]);

export type RouteDecision = { type: "next" } | { type: "redirect"; location: string };

const NEXT: RouteDecision = { type: "next" };

/**
 * Pure routing decision behind the optimistic proxy guard. The API remains the real
 * authority; a stale hint here is corrected later by the session-expired flow.
 */
export function routeDecision(
  pathname: string,
  search: string,
  hasSession: boolean,
): RouteDecision {
  if (isProtectedPath(pathname) && !hasSession) {
    return { type: "redirect", location: loginRedirectUrl(`${pathname}${search}`) };
  }
  if (AUTH_PATHS.has(pathname) && hasSession) {
    return { type: "redirect", location: DASHBOARD_PATH };
  }
  return NEXT;
}
