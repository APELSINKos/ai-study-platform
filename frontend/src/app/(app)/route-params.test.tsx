import { describe, expect, it, vi } from "vitest";

import ChatPage from "./chat/page";
import DocumentDetailPage from "./documents/[id]/page";
import WorkspacePage from "./workspaces/[id]/page";

vi.mock("next-intl/server", () => ({ getTranslations: vi.fn() }));

type Param = string | string[] | undefined;

describe("the document page", () => {
  const cases: [Param, number | null][] = [
    ["7", 7],
    ["0", 0],
    ["1e3", null],
    ["-1", null],
    [" 1 ", null],
    [["1", "2"], null],
    [undefined, null],
  ];

  it.each(cases)("opens the document for ?fragment=%j at %j", async (fragment, expected) => {
    const page = await DocumentDetailPage({
      params: Promise.resolve({ id: "d1" }),
      searchParams: Promise.resolve({ fragment }),
    });

    expect(page.props).toEqual({ id: "d1", fragment: expected });
  });
});

describe("the workspace page", () => {
  const cases: [Param, string | null][] = [
    ["  light reactions  ", "light reactions"],
    ["   ", null],
    [["light", "dark"], null],
    [undefined, null],
  ];

  it.each(cases)("searches for ?q=%j as %j", async (q, expected) => {
    const page = await WorkspacePage({
      params: Promise.resolve({ id: "w1" }),
      searchParams: Promise.resolve({ q }),
    });

    expect(page.props).toEqual({ id: "w1", query: expected });
  });
});

describe("the chat page", () => {
  const sessionId = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
  const workspaceId = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d";

  it("parses absent, uppercase and malformed ?session= and ?workspace= params", async () => {
    const empty = await ChatPage({ searchParams: Promise.resolve({}) });
    expect(empty.props).toEqual({ sessionParam: { kind: "none" }, initialWorkspaceId: null });

    const valid = await ChatPage({
      searchParams: Promise.resolve({
        session: sessionId.toUpperCase(),
        workspace: workspaceId.toUpperCase(),
      }),
    });
    expect(valid.props).toEqual({
      sessionParam: { kind: "valid", id: sessionId },
      initialWorkspaceId: workspaceId,
    });

    const malformed = await ChatPage({
      searchParams: Promise.resolve({
        session: "not-a-uuid",
        workspace: "also-not-a-uuid",
      }),
    });
    expect(malformed.props).toEqual({
      sessionParam: { kind: "invalid" },
      initialWorkspaceId: null,
    });
  });
});
