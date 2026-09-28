"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { loginRedirectUrl } from "@/features/auth/constants";
import { isProtectedPath } from "@/features/auth/protected-paths";
import { onSessionExpired } from "@/lib/api/session-events";
import { makeQueryClient } from "@/lib/query-client";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const router = useRouter();
  const pathname = usePathname();
  // Set while a redirect to the login page is in flight, so that the requests still
  // failing on the old page do not queue more redirects.
  const redirectingRef = useRef(false);

  useEffect(() => {
    redirectingRef.current = false;
  }, [pathname]);

  useEffect(
    () =>
      onSessionExpired(() => {
        // Public pages, the login page included, simply stay signed out.
        if (redirectingRef.current || !isProtectedPath(window.location.pathname)) {
          return;
        }
        redirectingRef.current = true;
        const next = `${window.location.pathname}${window.location.search}`;
        // Clearing the cache first would make the still-mounted page refetch at once.
        router.replace(loginRedirectUrl(next));
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
