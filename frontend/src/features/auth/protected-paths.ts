const PROTECTED_PREFIXES = [
  "/dashboard",
  "/workspaces",
  "/documents",
  "/chat",
  "/quizzes",
  "/flashcards",
  "/settings",
] as const;

/** True for a protected route or any of its sub-paths (`/dashboard/x`, not `/dashboardx`). */
export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
