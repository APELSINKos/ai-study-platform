import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  documentFixture,
  documentPageFixture,
  readyDocumentFixture,
} from "@/features/documents/test-fixtures";
import { workspaceFixture, workspacePageFixture } from "@/features/workspaces/test-fixtures";
import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type {
  ChatSessionDetailOut,
  ChatSessionOut,
  ChatSessionUpdateRequest,
  DocumentOut,
  MetaOut,
  WorkspaceOut,
} from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";
import { renderWithIntl } from "@/test/render";

import { ChatView } from "./chat-view";
import {
  CHAT_META_FIXTURE,
  chatMessageFixture,
  chatSessionDetailFixture,
  chatSessionFixture,
  chatSessionPageFixture,
  chatTurnFixture,
} from "./test-fixtures";
import type { SessionParam } from "./url-params";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));

const apiFetchMock = vi.mocked(apiFetch);

const WORKSPACE_A = workspaceFixture(1, {
  name: "Psychology 101",
  stats: { document_count: 2, ready_count: 2 },
});
const WORKSPACE_B = workspaceFixture(2, {
  name: "Organic chemistry",
  stats: { document_count: 1, ready_count: 1 },
});

const DOC_1 = readyDocumentFixture(1, {
  workspace_id: WORKSPACE_A.id,
  title: "Forgetting curve",
});
const DOC_2 = readyDocumentFixture(2, {
  workspace_id: WORKSPACE_A.id,
  title: "Spaced repetition",
});
const DOC_PROCESSING = documentFixture(3, {
  workspace_id: WORKSPACE_A.id,
  status: "processing",
  title: "Processing lecture",
});

const SESSION_1 = chatSessionDetailFixture(1, {
  workspace_id: WORKSPACE_A.id,
  workspace_name: WORKSPACE_A.name,
  title: "Ebbinghaus study",
  messages: [],
});
const SESSION_2 = chatSessionDetailFixture(2, {
  workspace_id: WORKSPACE_B.id,
  workspace_name: WORKSPACE_B.name,
  title: "Alkenes review",
  messages: [],
});

function primaryActions(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-variant="primary"]')).map(
    (element) => element.textContent ?? "",
  );
}

function renderChat({
  sessionParam = { kind: "none" } as SessionParam,
  initialWorkspaceId = null as string | null,
  locale = "en" as Locale,
} = {}) {
  const rendered = renderWithIntl(
    <ChatView sessionParam={sessionParam} initialWorkspaceId={initialWorkspaceId} />,
    { locale },
  );
  return {
    ...rendered,
    navigate: (nextSessionParam: SessionParam, nextWorkspaceId: string | null = null) =>
      rendered.rerender(
        <ChatView sessionParam={nextSessionParam} initialWorkspaceId={nextWorkspaceId} />,
      ),
  };
}

interface MockServerState {
  meta?: MetaOut;
  workspaces?: WorkspaceOut[];
  documentsByWorkspace?: Record<string, DocumentOut[]>;
  sessions?: ChatSessionDetailOut[];
}

function serveChat(initial: MockServerState = {}) {
  const meta = initial.meta ?? CHAT_META_FIXTURE;
  const workspaces = initial.workspaces ?? [WORKSPACE_A, WORKSPACE_B];
  const documentsByWorkspace = initial.documentsByWorkspace ?? {
    [WORKSPACE_A.id]: [DOC_1, DOC_2, DOC_PROCESSING],
    [WORKSPACE_B.id]: [],
  };
  let sessions = (initial.sessions ?? [SESSION_1, SESSION_2]).map((s) => ({ ...s }));

  apiFetchMock.mockImplementation(async (path, init) => {
    if (path === "/meta") {
      return meta;
    }
    if (path.startsWith("/workspaces?")) {
      return workspacePageFixture(workspaces);
    }
    const docsMatch = /^\/workspaces\/([^/]+)\/documents\?(.*)$/.exec(path);
    if (docsMatch) {
      const workspaceId = decodeURIComponent(docsMatch[1] ?? "");
      const docs = documentsByWorkspace[workspaceId] ?? [];
      return documentPageFixture(docs);
    }
    if (path.startsWith("/chat/sessions?")) {
      const url = new URL(`http://example.org${path}`);
      const wsFilter = url.searchParams.get("workspace_id");
      const filtered = wsFilter ? sessions.filter((s) => s.workspace_id === wsFilter) : sessions;
      return chatSessionPageFixture(filtered);
    }
    if (path === "/chat/sessions" && init?.method === "POST") {
      const body = init.json as { workspace_id: string; document_ids?: string[] | null };
      const ws = workspaces.find((w) => w.id === body.workspace_id) ?? WORKSPACE_A;
      const created = chatSessionDetailFixture(sessions.length + 10, {
        workspace_id: ws.id,
        workspace_name: ws.name,
        title: null,
        document_ids: body.document_ids ?? null,
        messages: [],
      });
      sessions = [created, ...sessions];
      const { messages: _messages, ...summary } = created;
      void _messages;
      return summary;
    }
    const messagesMatch = /^\/chat\/sessions\/([^/]+)\/messages$/.exec(path);
    if (messagesMatch && init?.method === "POST") {
      const sessionId = decodeURIComponent(messagesMatch[1] ?? "");
      const found = sessions.find((s) => s.id === sessionId);
      if (!found) {
        throw new ApiError({ status: 404, code: "chat_session_not_found", message: "Not found" });
      }
      const body = init.json as { content: string };
      const turn = chatTurnFixture(
        found,
        { content: body.content },
        {
          content: "Spaced review slows forgetting [1].",
          retrieval_ms: 40,
          generation_ms: 20,
        },
      );
      found.title = turn.session.title;
      found.message_count = turn.session.message_count;
      found.updated_at = turn.session.updated_at;
      found.messages = [...found.messages, turn.user_message, turn.assistant_message];
      return turn;
    }
    const detailMatch = /^\/chat\/sessions\/([^/]+)$/.exec(path);
    if (detailMatch) {
      const sessionId = decodeURIComponent(detailMatch[1] ?? "");
      const found = sessions.find((s) => s.id === sessionId);
      if (init?.method === "DELETE") {
        sessions = sessions.filter((s) => s.id !== sessionId);
        return undefined;
      }
      if (!found) {
        throw new ApiError({ status: 404, code: "chat_session_not_found", message: "Not found" });
      }
      if (init?.method === "PATCH") {
        const patch = init.json as ChatSessionUpdateRequest;
        if ("title" in patch) {
          found.title = patch.title ?? null;
        }
        if ("document_ids" in patch) {
          found.document_ids = patch.document_ids ?? null;
        }
        const { messages: _messages, ...summary } = found;
        void _messages;
        return summary;
      }
      return { ...found, messages: [...found.messages] };
    }
    throw new Error(`Unexpected apiFetch path: ${path}`);
  });
}

describe("ChatView", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    push.mockReset();
    replace.mockReset();
  });

  describe("index mode", () => {
    it("shows a warm empty state linking to /workspaces?new=1 when user has zero workspaces", async () => {
      serveChat({ workspaces: [], sessions: [] });
      renderChat();

      expect(
        await screen.findByRole("heading", { level: 2, name: "Start with a workspace" }),
      ).toBeInTheDocument();
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      const createLink = screen.getByRole("link", { name: "Create workspace" });
      expect(createLink).toHaveAttribute("href", "/workspaces?new=1");
      expect(primaryActions()).toEqual(["Create workspace"]);
    });

    it("opens New chat automatically when user has workspaces but no sessions, without auto-POST", async () => {
      serveChat({ sessions: [] });
      renderChat();

      expect(await screen.findByRole("button", { name: "Start chat" })).toBeInTheDocument();
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(primaryActions()).toEqual(["Start chat"]);
      expect(
        apiFetchMock.mock.calls.filter(
          ([path, init]) => path === "/chat/sessions" && init?.method === "POST",
        ),
      ).toHaveLength(0);
    });

    it("pre-selects ?workspace= in New chat form, creates session on submit, and navigates", async () => {
      serveChat({ sessions: [SESSION_1] });
      renderChat({ initialWorkspaceId: WORKSPACE_B.id });

      const select = await screen.findByLabelText("Workspace");
      expect(select).toHaveValue(WORKSPACE_B.id);
      expect(primaryActions()).toEqual(["Start chat"]);

      await userEvent.click(screen.getByRole("button", { name: "Start chat" }));

      await waitFor(() =>
        expect(push).toHaveBeenCalledWith(expect.stringMatching(/^\/chat\?session=/)),
      );
      expect(apiFetchMock).toHaveBeenCalledWith("/chat/sessions", {
        method: "POST",
        json: { workspace_id: WORKSPACE_B.id, document_ids: null },
      });
    });

    it("lists sessions with zero middle dots, toggles New chat with <=1 primary button, and filters by workspace", async () => {
      serveChat();
      renderChat();

      const list = await screen.findByRole("list", { name: "Chat sessions" });
      expect(within(list).getByRole("link", { name: "Ebbinghaus study" })).toHaveAttribute(
        "href",
        `/chat?session=${SESSION_1.id}`,
      );
      expect(within(list).getByRole("link", { name: "Alkenes review" })).toBeInTheDocument();
      expect(list.textContent).not.toContain("·");
      expect(primaryActions()).toEqual(["New chat"]);

      // Opening New chat switches the sole primary action to Start chat.
      await userEvent.click(screen.getByRole("button", { name: "New chat" }));
      expect(primaryActions()).toEqual(["Start chat"]);

      // Closing returns focus to New chat.
      await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
      expect(screen.getByRole("button", { name: "New chat" })).toHaveFocus();
      expect(primaryActions()).toEqual(["New chat"]);

      // Filtering narrows sessions by workspace_id.
      await userEvent.selectOptions(screen.getByLabelText("Filter by workspace"), WORKSPACE_B.id);
      await waitFor(() =>
        expect(
          within(screen.getByRole("list", { name: "Chat sessions" })).queryByText(
            "Ebbinghaus study",
          ),
        ).not.toBeInTheDocument(),
      );
      expect(screen.getByRole("link", { name: "Alkenes review" })).toBeInTheDocument();
    });

    it("enforces max_scope_documents and submits checked ready documents", async () => {
      serveChat({
        meta: {
          ...CHAT_META_FIXTURE,
          chat: { ...CHAT_META_FIXTURE.chat, max_scope_documents: 1 },
        },
        sessions: [],
      });
      renderChat();

      await screen.findByRole("button", { name: "Start chat" });
      await userEvent.click(screen.getByRole("radio", { name: "Selected documents" }));

      const doc1Box = await screen.findByRole("checkbox", { name: "Forgetting curve" });
      const doc2Box = screen.getByRole("checkbox", { name: "Spaced repetition" });
      // Processing document is excluded from ready scope picker.
      expect(
        screen.queryByRole("checkbox", { name: "Processing lecture" }),
      ).not.toBeInTheDocument();

      await userEvent.click(doc1Box);
      expect(doc1Box).toBeChecked();
      // At cap of 1, the second checkbox is disabled while the checked one remains toggleable.
      expect(doc2Box).toBeDisabled();

      await userEvent.click(screen.getByRole("button", { name: "Start chat" }));

      await waitFor(() => expect(push).toHaveBeenCalled());
      expect(apiFetchMock).toHaveBeenCalledWith("/chat/sessions", {
        method: "POST",
        json: { workspace_id: WORKSPACE_A.id, document_ids: [DOC_1.id] },
      });
    });

    it("deletes a session from the index list and returns focus to the page heading", async () => {
      serveChat({ sessions: [SESSION_1] });
      renderChat();

      await screen.findByRole("link", { name: "Ebbinghaus study" });
      await userEvent.click(screen.getByRole("button", { name: "Delete Ebbinghaus study" }));
      const dialog = await screen.findByRole("alertdialog", { name: "Delete this chat?" });
      await userEvent.click(within(dialog).getByRole("button", { name: "Delete chat" }));

      await waitFor(() =>
        expect(apiFetchMock).toHaveBeenCalledWith(`/chat/sessions/${SESSION_1.id}`, {
          method: "DELETE",
        }),
      );
      await waitFor(() =>
        expect(screen.getByRole("heading", { level: 1, name: "Chat" })).toHaveFocus(),
      );
    });
  });

  describe("active session mode", () => {
    it("renders Not found immediately for malformed ?session= without calling the API", () => {
      renderChat({ sessionParam: { kind: "invalid" } });

      expect(screen.getByRole("heading", { level: 1, name: "Chat not found" })).toBeInTheDocument();
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(primaryActions()).toEqual(["All chats"]);
      expect(apiFetchMock).not.toHaveBeenCalled();
    });

    it("keeps one sr-only h1 and zero primary actions while loading or on load error", async () => {
      apiFetchMock.mockReturnValueOnce(new Promise(() => {}));
      const { unmount } = renderChat({ sessionParam: { kind: "valid", id: SESSION_1.id } });
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(primaryActions()).toEqual([]);
      unmount();

      apiFetchMock.mockRejectedValueOnce(
        new ApiError({ status: 500, code: "internal_error", message: "Backend secret error" }),
      );
      renderChat({ sessionParam: { kind: "valid", id: SESSION_1.id } });

      expect(await screen.findByRole("alert")).toHaveTextContent("This chat could not be loaded.");
      expect(screen.queryByText("Backend secret error")).not.toBeInTheDocument();
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(primaryActions()).toEqual([]);
    });

    it("shows Not found even if a cached copy existed once refetch returns chat_session_not_found", async () => {
      serveChat({ sessions: [SESSION_1] });
      const { queryClient } = renderChat({ sessionParam: { kind: "valid", id: SESSION_1.id } });

      await screen.findByRole("heading", { level: 1, name: "Ebbinghaus study" });

      apiFetchMock.mockRejectedValue(
        new ApiError({ status: 404, code: "chat_session_not_found", message: "Gone" }),
      );
      await act(() =>
        queryClient.refetchQueries({ queryKey: queryKeys.chatSession(SESSION_1.id) }),
      );

      expect(
        await screen.findByRole("heading", { level: 1, name: "Chat not found" }),
      ).toBeInTheDocument();
    });

    it("keeps Send as the sole primary button across Rename, Scope and Sessions drawer states", async () => {
      serveChat({ sessions: [SESSION_1, SESSION_2] });
      renderChat({ sessionParam: { kind: "valid", id: SESSION_1.id } });

      await screen.findByRole("heading", { level: 1, name: "Ebbinghaus study" });
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(primaryActions()).toEqual(["Send"]);

      // Margin note links to workspace and shows scope summary.
      const wsLink = screen.getByRole("link", { name: "Workspace: Psychology 101" });
      expect(wsLink).toHaveAttribute("href", `/workspaces/${WORKSPACE_A.id}`);
      expect(document.querySelector(".margin-note")).toHaveTextContent("All ready documents");

      // Rename inline editor Save button must be secondary, returning focus on close.
      await userEvent.click(screen.getByRole("button", { name: "Rename" }));
      expect(screen.getByRole("button", { name: "Save" }).dataset.variant).toBe("secondary");
      expect(primaryActions()).toEqual(["Send"]);

      const input = screen.getByLabelText("Chat title");
      await userEvent.clear(input);
      await userEvent.type(input, "Memory exam prep");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));

      expect(
        await screen.findByRole("heading", { level: 1, name: "Memory exam prep" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Rename" })).toHaveFocus();

      // Sessions drawer New chat link must be secondary.
      await userEvent.click(screen.getByRole("button", { name: "Sessions" }));
      const drawer = await screen.findByRole("dialog", { name: "Chat sessions" });
      expect(within(drawer).getByRole("link", { name: "New chat" }).dataset.variant).toBe(
        "secondary",
      );
      expect(primaryActions()).toEqual(["Send"]);
      await userEvent.click(within(drawer).getByRole("button", { name: "Close sessions" }));
    });

    it("intersects stale deleted document IDs in Scope Editor and converts empty to null", async () => {
      const deletedDocId = "00000000-0000-4000-9000-000000000999";
      const scopedSession = chatSessionDetailFixture(3, {
        workspace_id: WORKSPACE_A.id,
        workspace_name: WORKSPACE_A.name,
        title: "Scoped session",
        document_ids: [DOC_1.id, deletedDocId],
        messages: [],
      });
      serveChat({ sessions: [scopedSession] });
      renderChat({ sessionParam: { kind: "valid", id: scopedSession.id } });

      await screen.findByRole("heading", { level: 1, name: "Scoped session" });
      await userEvent.click(screen.getByRole("button", { name: "Scope" }));
      expect(screen.getByRole("button", { name: "Save" }).dataset.variant).toBe("secondary");
      expect(primaryActions()).toEqual(["Send"]);

      await screen.findByRole("checkbox", { name: "Forgetting curve" });
      await userEvent.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(apiFetchMock).toHaveBeenCalledWith(`/chat/sessions/${scopedSession.id}`, {
          method: "PATCH",
          json: { document_ids: [DOC_1.id] },
        }),
      );
      expect(screen.getByRole("button", { name: "Scope" })).toHaveFocus();

      // Now uncheck the last remaining document: submitting converts empty selection to null.
      await userEvent.click(screen.getByRole("button", { name: "Scope" }));
      const doc1Box = await screen.findByRole("checkbox", { name: "Forgetting curve" });
      await userEvent.click(doc1Box);
      await userEvent.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(apiFetchMock).toHaveBeenCalledWith(`/chat/sessions/${scopedSession.id}`, {
          method: "PATCH",
          json: { document_ids: null },
        }),
      );
    });

    it("deletes active session via AlertDialog and replaces URL with /chat", async () => {
      serveChat({ sessions: [SESSION_1] });
      renderChat({ sessionParam: { kind: "valid", id: SESSION_1.id } });

      await screen.findByRole("heading", { level: 1, name: "Ebbinghaus study" });
      await userEvent.click(screen.getByRole("button", { name: "Delete" }));
      const dialog = await screen.findByRole("alertdialog", { name: "Delete this chat?" });
      await userEvent.click(within(dialog).getByRole("button", { name: "Delete chat" }));

      await waitFor(() => expect(replace).toHaveBeenCalledWith("/chat"));
    });

    it("sends a grounded turn without AbortSignal, ignores IME Enter, and announces reply", async () => {
      serveChat({
        sessions: [
          chatSessionDetailFixture(1, {
            workspace_id: WORKSPACE_A.id,
            workspace_name: WORKSPACE_A.name,
            title: null,
            messages: [],
          }),
        ],
      });
      renderChat({ sessionParam: { kind: "valid", id: SESSION_1.id } });

      await screen.findByRole("heading", { level: 1, name: "New chat" });
      const box = screen.getByLabelText("Your question");
      await userEvent.type(box, "How does review help?");

      // IME composition Enter must not submit.
      fireEvent.keyDown(box, { key: "Enter", isComposing: true });
      expect(apiFetchMock.mock.calls.filter(([path]) => path.endsWith("/messages"))).toHaveLength(
        0,
      );

      await userEvent.click(screen.getByRole("button", { name: "Send" }));

      expect(await screen.findByText(/Spaced review slows forgetting/)).toBeInTheDocument();
      const postCall = apiFetchMock.mock.calls.find(([path]) => path.endsWith("/messages"));
      expect(postCall?.[1]).toEqual({
        method: "POST",
        json: { content: "How does review help?" },
      });
      // Metadata footer uses separate spans with zero middle dots.
      expect(screen.getByText("60 ms")).toBeInTheDocument();
      expect(screen.getByText("1 source")).toBeInTheDocument();
      expect(screen.getByText("Offline answer")).toBeInTheDocument();
      expect(document.body.textContent).not.toContain("·");
      expect(screen.getByRole("status")).toHaveTextContent("Answer received with 1 source.");
    });

    it("preserves per-session drafts and in-flight pending state across session switches", async () => {
      const pendingTurn = Promise.withResolvers<ReturnType<typeof chatTurnFixture>>();
      serveChat({ sessions: [SESSION_1, SESSION_2] });
      const baseImpl = apiFetchMock.getMockImplementation();
      apiFetchMock.mockImplementation((path, init) => {
        if (path === `/chat/sessions/${SESSION_1.id}/messages` && init?.method === "POST") {
          return pendingTurn.promise;
        }
        return baseImpl ? baseImpl(path, init) : Promise.reject(new Error("no impl"));
      });

      const { navigate } = renderChat({ sessionParam: { kind: "valid", id: SESSION_1.id } });
      await screen.findByRole("heading", { level: 1, name: "Ebbinghaus study" });

      await userEvent.type(screen.getByLabelText("Your question"), "In-flight question");
      await userEvent.click(screen.getByRole("button", { name: "Send" }));

      // Pending bubble shows and Send stays enabled (aria-busy, not native disabled).
      expect(await screen.findByText("In-flight question")).toBeInTheDocument();
      const sendBtn = screen.getByRole("button", { name: "Send" });
      expect(sendBtn).toHaveAttribute("aria-busy", "true");
      expect(sendBtn).not.toBeDisabled();

      // Switch to session 2, type an unsent draft there.
      navigate({ kind: "valid", id: SESSION_2.id });
      await screen.findByRole("heading", { level: 1, name: "Alkenes review" });
      expect(screen.queryByText("In-flight question")).not.toBeInTheDocument();
      await userEvent.type(screen.getByLabelText("Your question"), "Draft for session two");

      // Switch back to session 1 while turn is still pending: pending bubble & loading persist!
      navigate({ kind: "valid", id: SESSION_1.id });
      await screen.findByRole("heading", { level: 1, name: "Ebbinghaus study" });
      expect(screen.getByText("In-flight question")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Send" })).toHaveAttribute("aria-busy", "true");

      // Resolve the turn while back on session 1.
      const resolvedTurn = chatTurnFixture(
        SESSION_1,
        { content: "In-flight question" },
        { content: "Grounded follow-up answer [1]." },
      );
      await act(async () => {
        pendingTurn.resolve(resolvedTurn);
        await pendingTurn.promise;
      });
      expect(await screen.findByText(/Grounded follow-up answer/)).toBeInTheDocument();

      // Switch back to session 2: unsent draft is still intact!
      navigate({ kind: "valid", id: SESSION_2.id });
      await screen.findByRole("heading", { level: 1, name: "Alkenes review" });
      expect(screen.getByLabelText("Your question")).toHaveValue("Draft for session two");
    });

    it("restores draft and shows translated error on send failure without leaking error.message", async () => {
      serveChat({ sessions: [SESSION_1] });
      const baseImpl = apiFetchMock.getMockImplementation();
      apiFetchMock.mockImplementation((path, init) => {
        if (path.endsWith("/messages") && init?.method === "POST") {
          return Promise.reject(
            new ApiError({
              status: 503,
              code: "chat_unavailable",
              message: "Upstream gateway exploded",
              retryAfterSeconds: 30,
            }),
          );
        }
        return baseImpl ? baseImpl(path, init) : Promise.reject(new Error("no impl"));
      });

      renderChat({ sessionParam: { kind: "valid", id: SESSION_1.id } });
      await screen.findByRole("heading", { level: 1, name: "Ebbinghaus study" });
      await userEvent.type(screen.getByLabelText("Your question"), "Keep this question");
      await userEvent.click(screen.getByRole("button", { name: "Send" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The AI chat service is temporarily unavailable. Try again in 30 seconds.",
      );
      expect(screen.queryByText("Upstream gateway exploded")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Your question")).toHaveValue("Keep this question");
    });

    it("never leaks raw backend content on insufficient_context for both model=null and model!=null", async () => {
      const sessionWithInsufficient = chatSessionDetailFixture(5, {
        workspace_id: WORKSPACE_A.id,
        workspace_name: WORKSPACE_A.name,
        title: "Insufficient check",
        messages: [
          chatMessageFixture(1, { role: "user", content: "Recipe for soup?" }),
          chatMessageFixture(2, {
            role: "assistant",
            content: "RAW_BACKEND_ENGLISH_SKIPPED_LLM",
            citations: [],
            insufficient_context: true,
            model: null,
          }),
          chatMessageFixture(3, { role: "user", content: "Uncovered detail?" }),
          chatMessageFixture(4, {
            role: "assistant",
            content: "RAW_BACKEND_ENGLISH_MODEL_REFUSED",
            citations: [],
            insufficient_context: true,
            model: "mock-heuristic-v1",
          }),
        ],
      });
      serveChat({ sessions: [sessionWithInsufficient] });
      renderChat({ sessionParam: { kind: "valid", id: sessionWithInsufficient.id }, locale: "ru" });

      await screen.findByRole("heading", { level: 1, name: "Insufficient check" });
      expect(screen.queryByText("RAW_BACKEND_ENGLISH_SKIPPED_LLM")).not.toBeInTheDocument();
      expect(screen.queryByText("RAW_BACKEND_ENGLISH_MODEL_REFUSED")).not.toBeInTheDocument();
      expect(
        screen.getByText(/В выбранных материалах не нашлось подходящих фрагментов/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/В ваших материалах недостаточно сведений, чтобы ответить/),
      ).toBeInTheDocument();
    });

    it("replaces composer with a calm limit notice when session reaches max_messages_per_session", async () => {
      const fullSession: ChatSessionDetailOut = chatSessionDetailFixture(6, {
        workspace_id: WORKSPACE_A.id,
        workspace_name: WORKSPACE_A.name,
        title: "Full chat",
        message_count: 200,
        messages: [chatMessageFixture(1), chatMessageFixture(2)],
      });
      serveChat({ sessions: [fullSession] });
      renderChat({ sessionParam: { kind: "valid", id: fullSession.id } });

      await screen.findByRole("heading", { level: 1, name: "Full chat" });
      expect(
        screen.getByText(/This chat has reached the limit of 200 messages/),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("Your question")).not.toBeInTheDocument();
      expect(primaryActions()).toEqual(["Start new chat"]);
    });

    it("speaks Russian across index and active session states", async () => {
      const sessionRu: ChatSessionOut = chatSessionFixture(1, {
        workspace_id: WORKSPACE_A.id,
        workspace_name: WORKSPACE_A.name,
        title: null,
        message_count: 3,
      });
      serveChat({
        sessions: [{ ...sessionRu, messages: [] }],
      });
      const { navigate } = renderChat({ locale: "ru" });

      expect(await screen.findByRole("heading", { level: 1, name: "Чат" })).toBeInTheDocument();
      expect(await screen.findByText("3 сообщения")).toBeInTheDocument();
      expect(primaryActions()).toEqual(["Новый чат"]);

      navigate({ kind: "valid", id: sessionRu.id });
      expect(
        await screen.findByRole("heading", { level: 1, name: "Новый чат" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Чаты" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Переименовать" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Материалы" })).toBeInTheDocument();
      expect(primaryActions()).toEqual(["Отправить"]);
    });
  });
});
