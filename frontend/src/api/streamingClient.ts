import type { AgentEvent } from "../types/chat";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/**
 * Start a new conversation.
 * Returns the conversation id + the initial assistant greeting.
 */
export async function startConversation() {
  const response = await fetch(`${API_BASE_URL}/chat/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Failed to start conversation: ${response.status}`);
  }
  return response.json() as Promise<{
    conversation_id: string;
    assistant_message: string;
  }>;
}

/**
 * Send a message and stream the agent's response.
 *
 * Yields parsed AgentEvent objects as they arrive. The consumer uses
 * `for await (const event of streamMessage(...))` to handle them.
 *
 * Why fetch+ReadableStream and not EventSource:
 *   EventSource only supports GET. We POST because the message is in
 *   the body. 20 lines of fetch is cleaner than the alternatives.
 */
export async function* streamMessage(
  conversationId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await fetch(
    `${API_BASE_URL}/chat/${conversationId}/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
      signal,
    },
  );

  if (!response.ok) {
    throw new Error(`Stream failed: ${response.status}`);
  }

  if (!response.body) {
    throw new Error("Response has no body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE messages are separated by blank lines (\n\n).
      // Process each complete message, keep the tail for the next iteration.
      const messages = buffer.split("\n\n");
      buffer = messages.pop() ?? "";

      for (const message of messages) {
        const trimmed = message.trim();
        if (!trimmed.startsWith("data:")) continue;

        const data = trimmed.slice("data:".length).trim();
        if (!data) continue;

        try {
          const parsed = JSON.parse(data) as AgentEvent;
          yield parsed;
        } catch (err) {
          console.warn("Failed to parse SSE event:", data, err);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}