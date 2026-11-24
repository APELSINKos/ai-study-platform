import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { ChatSessionDetailOut, ChatTurnOut } from "@/lib/api/types";
import { queryKeys } from "@/lib/query-keys";

import { useChatSession, useSendMessage } from "./hooks";
import { chatSessionDetailFixture, chatTurnFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const SESSION = chatSessionDetailFixture(1, {
  title: "Memory notes",
  messages: [],
});

function renderWithClient<T>(hook: () => T) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { ...renderHook(hook, { wrapper: Wrapper }), queryClient };
}

describe("useSendMessage", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("cancels an in-flight GET refetch started while sending so stale data cannot overwrite the new turn", async () => {
    const pendingPost = Promise.withResolvers<ChatTurnOut>();
    const staleRefetch = Promise.withResolvers<ChatSessionDetailOut>();
    let getCount = 0;
    let staleSignal: AbortSignal | undefined;

    apiFetchMock.mockImplementation((path, init) => {
      if (path === `/chat/sessions/${SESSION.id}/messages` && init?.method === "POST") {
        return pendingPost.promise;
      }
      if (path === `/chat/sessions/${SESSION.id}`) {
        getCount += 1;
        if (getCount === 1) {
          return Promise.resolve(SESSION);
        }
        staleSignal = init?.signal ?? undefined;
        return staleRefetch.promise;
      }
      throw new Error(`Unexpected path: ${path}`);
    });

    const { result, queryClient } = renderWithClient(() => ({
      session: useChatSession(SESSION.id),
      send: useSendMessage(SESSION.id),
    }));

    await waitFor(() => expect(result.current.session.data?.id).toBe(SESSION.id));

    // Start sending a message, then start a concurrent GET refetch while POST is in flight.
    act(() => {
      result.current.send.mutate({ sessionId: SESSION.id, content: "How does review help?" });
    });
    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(`/chat/sessions/${SESSION.id}/messages`, {
        method: "POST",
        json: { content: "How does review help?" },
      }),
    );

    void queryClient.refetchQueries({ queryKey: queryKeys.chatSession(SESSION.id) });
    await waitFor(() => expect(getCount).toBe(2));

    // POST finishes first and cancels the stale GET before appending the new turn.
    const turn = chatTurnFixture(
      SESSION,
      { content: "How does review help?" },
      { content: "Spaced review slows forgetting [1]." },
    );
    await act(async () => {
      pendingPost.resolve(turn);
      await pendingPost.promise;
    });

    await waitFor(() => expect(result.current.session.data?.messages).toHaveLength(2));
    expect(staleSignal?.aborted).toBe(true);

    // Even if the stale GET resolves later with 0 messages, the new turn remains intact.
    await act(async () => {
      staleRefetch.resolve(SESSION);
      await staleRefetch.promise;
    });

    expect(
      queryClient.getQueryData<ChatSessionDetailOut>(queryKeys.chatSession(SESSION.id))?.messages,
    ).toHaveLength(2);
  });

  it("invokes hook-level onError and onRestoreDraft even after unmounting while in flight", async () => {
    const pendingPost = Promise.withResolvers<ChatTurnOut>();
    apiFetchMock.mockReturnValue(pendingPost.promise);
    const onRestoreDraft = vi.fn();
    const onError = vi.fn();

    const { result, unmount } = renderWithClient(() =>
      useSendMessage(SESSION.id, { onRestoreDraft, onError }),
    );

    act(() => {
      result.current.mutate({ sessionId: SESSION.id, content: "Still in flight" });
    });
    unmount();

    const failure = new ApiError({
      status: 503,
      code: "chat_unavailable",
      message: "Backend down",
      retryAfterSeconds: 15,
    });
    await act(async () => {
      pendingPost.reject(failure);
      await pendingPost.promise.catch(() => {});
    });

    expect(onRestoreDraft).toHaveBeenCalledWith(SESSION.id, "Still in flight");
    expect(onError).toHaveBeenCalledWith(failure, {
      sessionId: SESSION.id,
      content: "Still in flight",
    });
  });
});
