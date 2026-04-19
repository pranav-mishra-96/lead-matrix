import { useEffect, useRef } from "react";

import { useChat } from "../hooks/useChat";
import { DebugPanel } from "./DebugPanel";
import { MessageBubble } from "./MessageBubble";
import { MessageInput } from "./MessageInput";

export function ChatWindow() {
  const {
    messages,
    isStreaming,
    error,
    profile,
    tier,
    sendMessage,
    resetConversation,
  } = useChat();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  return (
    <div className="layout">
      <div className="chat">
        <header className="chat__header">
          <h1 className="chat__title">Strategic Lead Matrix</h1>
          <button
            className="chat__reset"
            onClick={resetConversation}
            disabled={isStreaming}
          >
            New conversation
          </button>
        </header>

        <div className="chat__messages" ref={scrollRef}>
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
        </div>

        {error && (
          <div className="chat__error" role="alert">
            {error}
          </div>
        )}

        <div className="chat__input">
          <MessageInput onSend={sendMessage} disabled={isStreaming} />
        </div>
      </div>

      <DebugPanel profile={profile} tier={tier} />
    </div>
  );
}