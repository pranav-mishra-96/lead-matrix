import { useCallback, useEffect, useRef, useState } from "react";

import { startConversation, streamMessage } from "../api/streamingClient";
import type {
  ChatMessage,
  ProfileEvent,
  TierEvent,
} from "../types/chat";

// ---------------------------------------------------------------------------
// Tiny UUID helper — avoids a dep on uuid/crypto.randomUUID fallbacks
// ---------------------------------------------------------------------------
function tempId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

// ---------------------------------------------------------------------------
// Shape the hook returns to the UI
// ---------------------------------------------------------------------------
export interface UseChatResult {
  conversationId: string | null;
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  profile: ProfileEvent | null;
  tier: TierEvent | null;
  sendMessage: (content: string) => Promise<void>;
  resetConversation: () => void;
}

export function useChat(): UseChatResult {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState<ProfileEvent | null>(null);
  const [tier, setTier] = useState<TierEvent | null>(null);

  // Track the in-flight stream so we can cancel on unmount or reset
  const abortRef = useRef<AbortController | null>(null);

  // -------------------------------------------------------------------------
  // Initialize a conversation on first mount.
  //
  // StrictMode in dev invokes effects twice. We use the `cancelled` flag
  // to ignore the first run's result — the second invocation's request wins.
  // In production StrictMode is off, so the effect runs once normally.
  // -------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const result = await startConversation();
        if (cancelled) return;
        setConversationId(result.conversation_id);
        setMessages([
          {
            id: tempId(),
            role: "assistant",
            content: result.assistant_message,
          },
        ]);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to start chat");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // -------------------------------------------------------------------------
  // Cancel any in-flight stream when the component unmounts
  // -------------------------------------------------------------------------
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // -------------------------------------------------------------------------
  // Send a message and consume the streaming response
  // -------------------------------------------------------------------------
  const sendMessage = useCallback(
    async (content: string) => {
      if (!conversationId || isStreaming) return;

      const userMsg: ChatMessage = {
        id: tempId(),
        role: "user",
        content,
      };
      const assistantId = tempId();
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);
      setError(null);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        for await (const event of streamMessage(
          conversationId,
          content,
          controller.signal,
        )) {
          switch (event.type) {
            case "token": {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + event.content }
                    : m,
                ),
              );
              break;
            }
            case "profile": {
              setProfile(event);
              break;
            }
            case "tier": {
              setTier(event);
              break;
            }
            case "error": {
              setError(event.message);
              break;
            }
            case "done": {
              break;
            }
          }
        }
      } catch (err) {
        if (err instanceof Error && err.name !== "AbortError") {
          setError(err.message);
        }
      } finally {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, streaming: false } : m,
          ),
        );
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [conversationId, isStreaming],
  );

  // -------------------------------------------------------------------------
  // Reset — abandon the current conversation and start a fresh one
  // -------------------------------------------------------------------------
  const resetConversation = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setProfile(null);
    setTier(null);
    setError(null);
    setIsStreaming(false);
    setConversationId(null);

    (async () => {
      try {
        const result = await startConversation();
        setConversationId(result.conversation_id);
        setMessages([
          {
            id: tempId(),
            role: "assistant",
            content: result.assistant_message,
          },
        ]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to reset");
      }
    })();
  }, []);

  return {
    conversationId,
    messages,
    isStreaming,
    error,
    profile,
    tier,
    sendMessage,
    resetConversation,
  };
}