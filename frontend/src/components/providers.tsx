"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { onSessionExpired } from "@/lib/api/session-events";
import { makeQueryClient } from "@/lib/query-client";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const router = useRouter();

  useEffect(
    () =>
      onSessionExpired(() => {
        queryClient.clear();
        const next = `${window.location.pathname}${window.location.search}`;
        router.replace(`/login?next=${encodeURIComponent(next)}`);
      }),
    [queryClient, router],
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ThemeProvider>
  );
}
