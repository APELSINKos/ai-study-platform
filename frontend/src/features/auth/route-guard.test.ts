import { describe, expect, it } from "vitest";

import { routeDecision } from "./route-guard";

describe("routeDecision", () => {
  it("sends an anonymous visitor from a protected path to login, with next set", () => {
    expect(routeDecision("/dashboard", "", false)).toEqual({
      type: "redirect",
      location: "/login?next=%2Fdashboard",
    });
  });

  it("protects nested paths under a protected prefix", () => {
    expect(routeDecision("/settings/profile", "", false)).toEqual({
      type: "redirect",
      location: "/login?next=%2Fsettings%2Fprofile",
    });
  });

  it("preserves and encodes the search string in next", () => {
    expect(routeDecision("/dashboard", "?tab=progress", false)).toEqual({
      type: "redirect",
      location: `/login?next=${encodeURIComponent("/dashboard?tab=progress")}`,
    });
  });

  it("lets a signed-in visitor through to a protected path", () => {
    expect(routeDecision("/dashboard", "", true)).toEqual({ type: "next" });
  });

  it.each(["/", "/status", "/dashboardx"] as const)(
    "leaves the public path %s alone regardless of session",
    (pathname) => {
      expect(routeDecision(pathname, "", false)).toEqual({ type: "next" });
      expect(routeDecision(pathname, "", true)).toEqual({ type: "next" });
    },
  );

  it.each(["/login", "/register"] as const)(
    "sends a signed-in visitor away from %s to the dashboard",
    (pathname) => {
      expect(routeDecision(pathname, "", true)).toEqual({
        type: "redirect",
        location: "/dashboard",
      });
    },
  );

  it.each(["/login", "/register"] as const)("lets an anonymous visitor reach %s", (pathname) => {
    expect(routeDecision(pathname, "", false)).toEqual({ type: "next" });
  });
});
