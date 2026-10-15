import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/render";

import { NavList } from "./nav-list";

const navigation = { pathname: "/dashboard" };

vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));

const WORKSPACE_ID = "0b9df3d4-6f43-4c1e-9a52-2f1c5b7e8a10";
const DOCUMENT_ID = "7c1e2d3f-4a5b-4c6d-8e9f-a0b1c2d3e4f5";

function currentLinks(): string[] {
  return screen
    .getAllByRole("link")
    .filter((link) => link.getAttribute("aria-current") === "page")
    .map((link) => link.textContent ?? "");
}

describe("NavList", () => {
  beforeEach(() => {
    navigation.pathname = "/dashboard";
  });

  it("lists the dashboard and the workspaces in that order", () => {
    renderWithIntl(<NavList />);

    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Dashboard", "Workspaces"]);
    expect(screen.getByRole("link", { name: "Workspaces" })).toHaveAttribute("href", "/workspaces");
  });

  it.each([
    ["/dashboard", "Dashboard"],
    ["/workspaces", "Workspaces"],
    [`/workspaces/${WORKSPACE_ID}`, "Workspaces"],
    // A document lives inside a workspace, so its page belongs to the same section.
    [`/documents/${DOCUMENT_ID}`, "Workspaces"],
  ])("marks only the matching destination on %s", (pathname, expected) => {
    navigation.pathname = pathname;
    renderWithIntl(<NavList />);

    expect(currentLinks()).toEqual([expected]);
  });

  it.each([["/workspacesx"], ["/documentsx"], ["/settings"]])(
    "marks nothing on the unrelated path %s",
    (pathname) => {
      navigation.pathname = pathname;
      renderWithIntl(<NavList />);

      expect(currentLinks()).toEqual([]);
    },
  );

  it("speaks Russian", () => {
    navigation.pathname = "/workspaces";
    renderWithIntl(<NavList />, { locale: "ru" });

    expect(screen.getByRole("link", { name: "Пространства" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Панель" })).not.toHaveAttribute("aria-current");
  });
});
