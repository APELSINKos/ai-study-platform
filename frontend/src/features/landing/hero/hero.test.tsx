import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/render";

import { Hero } from "./hero";

describe("Hero", () => {
  it("sends new visitors to registration and returning ones to sign-in", () => {
    renderWithIntl(<Hero />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Read it once. Recall it on exam day.",
    );
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("keeps the illustrated lecture page out of the accessibility tree", () => {
    renderWithIntl(<Hero />);

    expect(screen.queryByText("How memory fades")).not.toBeNull();
    expect(screen.getByText("How memory fades").closest("[aria-hidden]")).not.toBeNull();
  });

  it("speaks Russian when the interface does", () => {
    renderWithIntl(<Hero />, { locale: "ru" });

    expect(screen.getByRole("link", { name: "Создать аккаунт" })).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.getByRole("link", { name: "Войти" })).toHaveAttribute("href", "/login");
  });
});
