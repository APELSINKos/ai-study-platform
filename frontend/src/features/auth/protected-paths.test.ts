import { describe, expect, it } from "vitest";

import { isProtectedPath } from "./protected-paths";

describe("isProtectedPath", () => {
  it.each([
    ["/dashboard", true],
    ["/dashboard/", true],
    ["/dashboard/settings", true],
    ["/dashboardx", false],
    ["/workspaces", true],
    ["/workspaces/1", true],
    ["/documents", true],
    ["/documents/1/edit", true],
    ["/chat", true],
    ["/chat/1", true],
    ["/quizzes", true],
    ["/quizzes/1", true],
    ["/flashcards", true],
    ["/flashcards/1", true],
    ["/settings", true],
    ["/settings/profile", true],
    ["/settingsx", false],
    ["/", false],
    ["/login", false],
    ["/register", false],
    ["/status", false],
  ] as const)("treats %j as protected: %s", (pathname, expected) => {
    expect(isProtectedPath(pathname)).toBe(expected);
  });
});
