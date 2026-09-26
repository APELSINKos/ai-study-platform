import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/render";

import { ThemeToggle } from "./theme-toggle";

const setTheme = vi.fn();

vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "dark", setTheme }) }));

describe("ThemeToggle", () => {
  it("marks the active theme", () => {
    renderWithIntl(<ThemeToggle />);

    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "false");
  });

  it("switches the theme", async () => {
    renderWithIntl(<ThemeToggle />);

    await userEvent.click(screen.getByRole("button", { name: "Light" }));

    expect(setTheme).toHaveBeenCalledWith("light");
  });
});
