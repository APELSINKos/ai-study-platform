import type {
  ChatMessageOut,
  ChatSessionDetailOut,
  ChatSessionOut,
  ChatSessionPage,
  ChatTurnOut,
  CitationOut,
  MetaOut,
} from "@/lib/api/types";

export const CHAT_WORKSPACE_ID = "00000000-0000-4000-8000-000000000001";
export const CHAT_DOCUMENT_ID = "00000000-0000-4000-9000-000000000001";

export const CHAT_META_FIXTURE: MetaOut = {
  max_upload_bytes: 20_971_520,
  allowed_extensions: [".pdf", ".md", ".txt"],
  max_pdf_pages: 500,
  max_active_documents_per_user: 10,
  max_storage_bytes_per_user: 1_073_741_824,
  ai: { mode: "offline", chat_model: "mock-heuristic-v1", embedding_model: "mock-hashing-v1" },
  search: { max_query_chars: 200 },
  chat: { max_message_chars: 2000, max_scope_documents: 50, max_messages_per_session: 200 },
};

export function citationFixture(index: number, overrides: Partial<CitationOut> = {}): CitationOut {
  return {
    index,
    chunk_id: `00000000-0000-4000-a000-${String(index).padStart(12, "0")}`,
    document_id: CHAT_DOCUMENT_ID,
    document_title: `Lecture ${index}`,
    chunk_index: index + 2,
    heading: `Lecture ${index} › Memory consolidation`,
    page_start: index,
    page_end: index,
    quote: `Spaced review slows down forgetting after passage ${index}.`,
    ...overrides,
  };
}

export function chatMessageFixture(
  sequence: number,
  overrides: Partial<ChatMessageOut> = {},
): ChatMessageOut {
  const isAssistant =
    (overrides.role ?? (sequence % 2 === 0 ? "assistant" : "user")) === "assistant";
  return {
    id: `00000000-0000-4000-c000-${String(sequence).padStart(12, "0")}`,
    sequence,
    role: isAssistant ? "assistant" : "user",
    content: isAssistant
      ? "Reviewing a lecture slows down forgetting [1]."
      : "How does reviewing slow down forgetting?",
    citations: isAssistant ? [citationFixture(1)] : [],
    insufficient_context: false,
    model: isAssistant ? "mock-heuristic-v1" : null,
    retrieval_ms: isAssistant ? 42 : null,
    generation_ms: isAssistant ? 18 : null,
    prompt_tokens: isAssistant ? 120 : null,
    completion_tokens: isAssistant ? 36 : null,
    created_at: "2026-11-24T10:00:00Z",
    ...overrides,
  };
}

export function chatSessionFixture(
  index: number,
  overrides: Partial<ChatSessionOut> = {},
): ChatSessionOut {
  return {
    id: `00000000-0000-4000-b000-${String(index).padStart(12, "0")}`,
    workspace_id: CHAT_WORKSPACE_ID,
    workspace_name: "Psychology 101",
    title: `Session ${index}`,
    document_ids: null,
    message_count: 2,
    created_at: "2026-11-24T09:00:00Z",
    updated_at: "2026-11-24T10:00:00Z",
    ...overrides,
  };
}

export function chatSessionDetailFixture(
  index: number,
  overrides: Partial<ChatSessionDetailOut> = {},
): ChatSessionDetailOut {
  const { messages, ...rest } = overrides;
  const base = chatSessionFixture(index, rest);
  const resolvedMessages = messages ?? [chatMessageFixture(1), chatMessageFixture(2)];
  return {
    ...base,
    message_count: overrides.message_count ?? resolvedMessages.length,
    messages: resolvedMessages,
  };
}

export function chatSessionPageFixture(
  items: ChatSessionOut[],
  { page = 1, pageSize = 20, total = items.length } = {},
): ChatSessionPage {
  return { items, total, page, page_size: pageSize };
}

export function chatTurnFixture(
  session: ChatSessionOut,
  userOverrides: Partial<ChatMessageOut> = {},
  assistantOverrides: Partial<ChatMessageOut> = {},
): ChatTurnOut {
  const nextSeq = session.message_count + 1;
  const user_message = chatMessageFixture(nextSeq, { role: "user", ...userOverrides });
  const assistant_message = chatMessageFixture(nextSeq + 1, {
    role: "assistant",
    ...assistantOverrides,
  });
  return {
    session: {
      ...session,
      title: session.title ?? user_message.content.slice(0, 80),
      message_count: session.message_count + 2,
      updated_at: assistant_message.created_at,
    },
    user_message,
    assistant_message,
  };
}
