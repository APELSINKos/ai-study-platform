"use client";

import { SignOutIcon } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useLogout } from "@/features/auth/hooks";
import type { UserOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export function UserMenu({ user, className }: { user: UserOut | undefined; className?: string }) {
  const t = useTranslations("AppShell.account");
  const router = useRouter();
  const logout = useLogout();
  const [error, setError] = useState<string | null>(null);

  if (!user) {
    return (
      <div className={cn("flex flex-col gap-2", className)}>
        <span className="sr-only">{t("loading")}</span>
        <div aria-hidden className="bg-ink/10 h-4 w-28 animate-pulse rounded" />
        <div aria-hidden className="bg-ink/10 h-3 w-36 animate-pulse rounded" />
      </div>
    );
  }

  function handleSignOut() {
    if (logout.isPending) {
      return;
    }
    setError(null);
    // The cache is only cleared once the server confirms the session is gone.
    logout.mutate(undefined, {
      onSuccess: () => router.push("/login"),
      onError: () => setError(t("signOutError")),
    });
  }

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="min-w-0">
        <p className="text-ink truncate text-sm font-medium">{user.display_name}</p>
        <p className="text-ink-soft truncate text-xs">{user.email}</p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="justify-start gap-2"
        isLoading={logout.isPending}
        onClick={handleSignOut}
      >
        {logout.isPending ? null : <SignOutIcon aria-hidden />}
        {t("signOut")}
      </Button>
      {error ? (
        <p role="alert" className="text-margin text-xs">
          {error}
        </p>
      ) : null}
    </div>
  );
}
