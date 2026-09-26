import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setLocale } from "@/i18n/actions";
import { renderWithIntl } from "@/test/render";

import { LocaleSwitcher } from "./locale-switcher";

const refresh = vi.fn();

vi.mock("@/i18n/actions", () => ({ setLocale: vi.fn(async () => undefined) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

describe("LocaleSwitcher", () => {
  beforeEach(() => {
    refresh.mockClear();
    vi.mocked(setLocale).mockClear();
  });

  it("marks the language in use", () => {
    renderWithIntl(<LocaleSwitcher />, { locale: "ru" });

    expect(screen.getByRole("group", { name: "Язык" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RU" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "false");
  });

  it("saves the chosen language and re-renders the page", async () => {
    renderWithIntl(<LocaleSwitcher />, { locale: "en" });

    await userEvent.click(screen.getByRole("button", { name: "RU" }));

    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(setLocale).toHaveBeenCalledWith("ru");
  });

  it("does nothing when the current language is chosen again", async () => {
    renderWithIntl(<LocaleSwitcher />, { locale: "en" });

    await userEvent.click(screen.getByRole("button", { name: "EN" }));

    expect(setLocale).not.toHaveBeenCalled();
  });
});
