export function TypingIndicator() {
  return (
    <span className="typing" aria-label="Assistant is typing">
      <span className="typing__dot" />
      <span className="typing__dot" />
      <span className="typing__dot" />
    </span>
  );
}