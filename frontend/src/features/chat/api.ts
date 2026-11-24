import { apiFetch } from "@/lib/api/client";
import type {
  ChatMessageCreateRequest,
  ChatSessionCreateRequest,
  ChatSessionDetailOut,
  ChatSessionOut,
  ChatSessionPage,
  ChatSessionUpdateRequest,
  ChatTurnOut,
} from "@/lib/api/types";

/** Encodes an id that may come from the address bar so it stays one path segment. */
function sessionPath(id: string): string {
  return `/chat/sessions/${encodeURIComponent(id)}`;
}

/** One page of the signed-in user's chat sessions, the most recently updated first. */
export function fetchChatSessionPage(
  workspaceId: string | null,
  page: number,
  pageSize: number,
  signal?: AbortSignal,
): Promise<ChatSessionPage> {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (workspaceId !== null) {
    query.set("workspace_id", workspaceId);
  }
  return apiFetch<ChatSessionPage>(`/chat/sessions?${query.toString()}`, { signal });
}

/** One chat session with all of its messages in chronological order. */
export function fetchChatSession(id: string, signal?: AbortSignal): Promise<ChatSessionDetailOut> {
  return apiFetch<ChatSessionDetailOut>(sessionPath(id), { signal });
}

/** Starts a new chat session scoped to a workspace or a selection of its documents. */
export function createChatSession(payload: ChatSessionCreateRequest): Promise<ChatSessionOut> {
  return apiFetch<ChatSessionOut>("/chat/sessions", { method: "POST", json: payload });
}

/** Renames a chat session or updates its document scope. */
export function updateChatSession(
  id: string,
  changes: ChatSessionUpdateRequest,
): Promise<ChatSessionOut> {
  return apiFetch<ChatSessionOut>(sessionPath(id), { method: "PATCH", json: changes });
}

/** Deletes a chat session and all of its messages. */
export function deleteChatSession(id: string): Promise<void> {
  return apiFetch<void>(sessionPath(id), { method: "DELETE" });
}

/**
 * Sends a question and waits for the grounded answer. Deliberately carries no unmount AbortSignal:
 * the backend commits the turn even if the user switches sessions before it finishes.
 */
export function sendChatMessage(
  sessionId: string,
  payload: ChatMessageCreateRequest,
): Promise<ChatTurnOut> {
  return apiFetch<ChatTurnOut>(`${sessionPath(sessionId)}/messages`, {
    method: "POST",
    json: payload,
  });
}
