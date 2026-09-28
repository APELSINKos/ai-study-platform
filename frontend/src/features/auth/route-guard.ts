import { isProtectedPath } from "./protected-paths";

const LOGIN_PATH = "/login";
const DASHBOARD_PATH = "/dashboard";
const AUTH_PATHS = new Set<string>(["/login", "/register"]);

export type RouteDecision = { type: "next" } | { type: "redirect"; location: string };

const NEXT: RouteDecision = { type: "next" };

/**
 * Pure routing decision behind the optimistic proxy guard: given the current path, its
 * search string and whether the session-hint cookie is present, decide whether the request
 * should continue or be redirected. The API remains the real authority; a stale hint here
 * is corrected later by the session-expired flow.
 */
export function routeDecision(
  pathname: string,
  search: string,
  hasSession: boolean,
): RouteDecision {
  if (isProtectedPath(pathname) && !hasSession) {
    const next = encodeURIComponent(`${pathname}${search}`);
    return { type: "redirect", location: `${LOGIN_PATH}?next=${next}` };
  }
  if (AUTH_PATHS.has(pathname) && hasSession) {
    return { type: "redirect", location: DASHBOARD_PATH };
  }
  return NEXT;
}
