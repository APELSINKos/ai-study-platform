/** The CSRF token cookie; also the only session hint visible to the proxy guard. */
export const CSRF_COOKIE_NAME = "recall_csrf";

export const LOGIN_PATH = "/login";
export const DASHBOARD_PATH = "/dashboard";

/** The login URL that carries the page to return to once signed in. */
export function loginRedirectUrl(next: string): string {
  return `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
}
