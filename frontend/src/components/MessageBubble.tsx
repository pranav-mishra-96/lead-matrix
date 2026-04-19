import type { ChatMessage } from "../types/chat";
import { TypingIndicator } from "./TypingIndicator";

interface Props {
  message: ChatMessage;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const showTyping = message.streaming && message.content === "";

  return (
    <div className={`bubble-row ${isUser ? "bubble-row--user" : "bubble-row--assistant"}`}>
      <div className={`bubble ${isUser ? "bubble--user" : "bubble--assistant"}`}>
        {showTyping ? <TypingIndicator /> : message.content}
        {message.streaming && message.content !== "" && (
          <span className="bubble__cursor" aria-hidden>▎</span>
        )}
      </div>
    </div>
  );
}