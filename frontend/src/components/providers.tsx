"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { isProtectedPath } from "@/features/auth/protected-paths";
import { onSessionExpired } from "@/lib/api/session-events";
import { makeQueryClient } from "@/lib/query-client";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const router = useRouter();
  // Survives effect re-runs (e.g. a route change gives useRouter a new reference)
  // so a second sessionExpired event never fires a second redirect.
  const redirectedRef = useRef(false);

  useEffect(
    () =>
      onSessionExpired(() => {
        // A public page (including the login page itself) just settles into a
        // signed-out state; redirecting here would fight a mounted useCurrentUser()
        // into a loop.
        if (redirectedRef.current) {
          return;
        }
        const pathname = window.location.pathname;
        if (!isProtectedPath(pathname)) {
          return;
        }
        redirectedRef.current = true;
        const next = `${pathname}${window.location.search}`;
        // Navigate away before dropping the cache: clearing first would rebuild the
        // still-mounted query with a fresh (stale) instance and trigger an immediate refetch.
        router.replace(`/login?next=${encodeURIComponent(next)}`);
        queryClient.clear();
      }),
    [queryClient, router],
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ThemeProvider>
  );
}
