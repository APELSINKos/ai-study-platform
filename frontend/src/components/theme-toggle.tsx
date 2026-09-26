"use client";

import { DesktopIcon, MoonIcon, SunIcon } from "@phosphor-icons/react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { SegmentedButton, SegmentedGroup } from "@/components/ui/segmented";

const THEMES = [
  { value: "light", Icon: SunIcon },
  { value: "dark", Icon: MoonIcon },
  { value: "system", Icon: DesktopIcon },
] as const;

const subscribeToNothing = () => () => {};

// The stored theme is only known in the browser; rendering it on the server would cause a hydration mismatch.
function useIsClient(): boolean {
  return useSyncExternalStore(
    subscribeToNothing,
    () => true,
    () => false,
  );
}

export function ThemeToggle() {
  const t = useTranslations("Theme");
  const { theme, setTheme } = useTheme();
  const isClient = useIsClient();

  return (
    <SegmentedGroup label={t("label")}>
      {THEMES.map(({ value, Icon }) => {
        const pressed = isClient && theme === value;
        return (
          <SegmentedButton
            key={value}
            aria-label={t(value)}
            title={t(value)}
            pressed={pressed}
            onClick={() => setTheme(value)}
          >
            <Icon aria-hidden className="size-4" weight={pressed ? "fill" : "regular"} />
          </SegmentedButton>
        );
      })}
    </SegmentedGroup>
  );
}
