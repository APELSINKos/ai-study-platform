import {
  useInfiniteQuery,
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";
import type {
  ChatSessionDetailOut,
  ChatSessionOut,
  ChatSessionPage,
  ChatSessionUpdateRequest,
} from "@/lib/api/types";
import { CHAT_SESSION_LIST_PAGE_SIZE, queryKeys } from "@/lib/query-keys";

import {
  createChatSession,
  deleteChatSession,
  fetchChatSession,
  fetchChatSessionPage,
  sendChatMessage,
  updateChatSession,
} from "./api";
import { CHAT_SESSION_NOT_FOUND_CODE } from "./error-message";

const FIRST_PAGE = 1;

type ChatSessionPages = InfiniteData<ChatSessionPage, number>;

export interface SendMessageVariables {
  sessionId: string;
  content: string;
}

function nextPageAfter(lastPage: ChatSessionPage): number | undefined {
  return lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined;
}

/**
 * Flattens loaded pages into one list. Offset pagination over sessions sorted by `updated_at` can
 * deliver the same session on two consecutive pages if another turn updates it mid-scroll; the
 * first occurrence stays.
 */
export function uniqueSessions(data: ChatSessionPages): ChatSessionOut[] {
  const seen = new Set<string>();
  return data.pages
    .flatMap((page) => page.items)
    .filter((session) => {
      if (seen.has(session.id)) {
        return false;
      }
      seen.add(session.id);
      return true;
    });
}

interface ChatQueryOptions {
  enabled?: boolean;
}

/** The user's chat sessions (all workspaces or one workspace), loaded a page at a time. */
export function useChatSessions(
  workspaceId: string | null,
  { enabled = true }: ChatQueryOptions = {},
) {
  const normalizedWorkspaceId = workspaceId?.toLowerCase() ?? null;
  return useInfiniteQuery({
    queryKey: queryKeys.chatSessions(normalizedWorkspaceId),
    queryFn: ({ pageParam, signal }) =>
      fetchChatSessionPage(normalizedWorkspaceId, pageParam, CHAT_SESSION_LIST_PAGE_SIZE, signal),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextPageAfter,
    select: uniqueSessions,
    enabled,
  });
}

/** One chat session with its full message history. */
export function useChatSession(id: string, { enabled = true }: ChatQueryOptions = {}) {
  const normalizedId = id.toLowerCase();
  return useQuery({
    queryKey: queryKeys.chatSession(normalizedId),
    queryFn: ({ signal }) => fetchChatSession(normalizedId, signal),
    enabled,
  });
}

/** Replaces a cached session row if present; never inserts one that was removed or never cached. */
function replaceCachedSessionInList(
  queryClient: QueryClient,
  listKey: readonly unknown[],
  updated: ChatSessionOut,
  moveToTop: boolean,
): void {
  queryClient.setQueryData<ChatSessionPages>(listKey, (data) => {
    if (data === undefined) {
      return undefined;
    }
    const exists = data.pages.some((page) => page.items.some((item) => item.id === updated.id));
    if (!exists) {
      return data;
    }
    if (!moveToTop) {
      return {
        ...data,
        pages: data.pages.map((page) => ({
          ...page,
          items: page.items.map((item) => (item.id === updated.id ? updated : item)),
        })),
      };
    }
    return {
      ...data,
      pages: data.pages.map((page, index) => {
        const without = page.items.filter((item) => item.id !== updated.id);
        return {
          ...page,
          items: index === 0 ? [updated, ...without] : without,
        };
      }),
    };
  });
}

function removeCachedSessionFromLists(queryClient: QueryClient, sessionId: string): void {
  for (const query of queryClient
    .getQueryCache()
    .findAll({ queryKey: queryKeys.chatSessionLists })) {
    queryClient.setQueryData<ChatSessionPages>(query.queryKey, (data) => {
      if (data === undefined) {
        return undefined;
      }
      const exists = data.pages.some((page) => page.items.some((item) => item.id === sessionId));
      if (!exists) {
        return data;
      }
      return {
        ...data,
        pages: data.pages.map((page) => ({
          ...page,
          items: page.items.filter((item) => item.id !== sessionId),
          total: Math.max(0, page.total - 1),
        })),
      };
    });
  }
}

export function useCreateChatSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createChatSession,
    onSuccess: (created) => {
      queryClient.setQueryData<ChatSessionDetailOut>(queryKeys.chatSession(created.id), {
        ...created,
        messages: [],
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatSessionLists });
    },
  });
}

export function useUpdateChatSession(id: string) {
  const queryClient = useQueryClient();
  const normalizedId = id.toLowerCase();
  return useMutation({
    mutationFn: (changes: ChatSessionUpdateRequest) => updateChatSession(normalizedId, changes),
    onSuccess: (updated) => {
      queryClient.setQueryData<ChatSessionDetailOut>(
        queryKeys.chatSession(updated.id),
        (current) => (current === undefined ? undefined : { ...current, ...updated }),
      );
      replaceCachedSessionInList(queryClient, queryKeys.chatSessions(null), updated, true);
      replaceCachedSessionInList(
        queryClient,
        queryKeys.chatSessions(updated.workspace_id),
        updated,
        true,
      );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatSessionLists });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatSession(normalizedId) });
    },
  });
}

export function useDeleteChatSession(id: string) {
  const queryClient = useQueryClient();
  const normalizedId = id.toLowerCase();
  return useMutation({
    mutationFn: async () => {
      try {
        await deleteChatSession(normalizedId);
      } catch (error) {
        // Already deleted elsewhere: what the user asked for is done.
        if (!(error instanceof ApiError && error.code === CHAT_SESSION_NOT_FOUND_CODE)) {
          throw error;
        }
      }
    },
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.chatSession(normalizedId) });
      removeCachedSessionFromLists(queryClient, normalizedId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatSessionLists });
    },
  });
}

interface UseSendMessageOptions {
  /** Hook-level error handler: still runs if the user switched sessions before a turn failed. */
  onRestoreDraft?: (sessionId: string, content: string) => void;
}

export function useSendMessage(sessionId: string, options: UseSendMessageOptions = {}) {
  const queryClient = useQueryClient();
  const normalizedId = sessionId.toLowerCase();
  return useMutation({
    mutationKey: queryKeys.chatSessionSend(normalizedId),
    retry: false,
    mutationFn: ({ sessionId: targetId, content }: SendMessageVariables) =>
      sendChatMessage(targetId.toLowerCase(), { content }),
    onSuccess: (turn, variables) => {
      const targetId = variables.sessionId.toLowerCase();
      queryClient.setQueryData<ChatSessionDetailOut>(queryKeys.chatSession(targetId), (current) => {
        if (current === undefined) {
          return undefined;
        }
        const existingIds = new Set(current.messages.map((message) => message.id));
        const appended = [turn.user_message, turn.assistant_message].filter(
          (message) => !existingIds.has(message.id),
        );
        return {
          ...current,
          ...turn.session,
          messages: [...current.messages, ...appended],
        };
      });
      replaceCachedSessionInList(queryClient, queryKeys.chatSessions(null), turn.session, true);
      replaceCachedSessionInList(
        queryClient,
        queryKeys.chatSessions(turn.session.workspace_id),
        turn.session,
        true,
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatSessionLists });
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspaceList });
      void queryClient.invalidateQueries({ queryKey: queryKeys.recentWorkspaces });
    },
    onError: (_error, variables) => {
      options.onRestoreDraft?.(variables.sessionId.toLowerCase(), variables.content);
    },
  });
}

/** Pending user message texts for one session, surviving remounts when switching sessions. */
export function usePendingChatMessages(sessionId: string): string[] {
  const normalizedId = sessionId.toLowerCase();
  return useMutationState({
    filters: {
      mutationKey: queryKeys.chatSessionSend(normalizedId),
      status: "pending",
    },
    select: (mutation) => {
      const variables = mutation.state.variables as SendMessageVariables | undefined;
      return variables?.content ?? "";
    },
  }).filter((content) => content.length > 0);
}
