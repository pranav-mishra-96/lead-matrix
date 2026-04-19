"""LLM client interface — abstract contract for any language model provider.

We define a Protocol here rather than an abstract base class because:
  - Protocols are structural (duck typing) — implementations don't need
    to inherit from LLMClient, just match the shape
  - Easier to mock in tests
  - Plays well with static type checkers without runtime overhead
"""
from collections.abc import AsyncIterator
from typing import Any, Protocol

from pydantic import BaseModel


# ----------------------------------------------------------------------------
# Data types — shared across all implementations
# ----------------------------------------------------------------------------
class ChatMessage(BaseModel):
    """A single message in a chat completion request.

    role is a plain str here (not our MessageRole enum) because LLM
    providers accept additional roles like "tool" and "function" that
    don't belong in our database schema.
    """

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


class LLMUsage(BaseModel):
    """Token accounting returned by most providers."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class LLMResponse(BaseModel):
    """Non-streaming response from the LLM."""

    content: str
    model: str
    usage: LLMUsage | None = None
    raw: dict[str, Any] | None = None  # full provider response for audit


# ----------------------------------------------------------------------------
# The Protocol — what every LLM client must implement
# ----------------------------------------------------------------------------
class LLMClient(Protocol):
    """Abstract LLM client.

    Any concrete client (OpenAIClient, ClaudeClient, LocalVLLMClient, MockClient)
    must provide these methods. The agent code depends on this Protocol,
    not on any specific provider.
    """

    model: str

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Single-shot chat completion — returns the full response at once.

        Used for structured extraction where we need the complete output
        before acting on it (e.g., parsing collected variables).
        """
        ...

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streaming chat completion — yields content chunks as they arrive.

        Used for the conversational turns where we want tokens to flow
        to the frontend in real time (low TTFT = better UX).
        """
        ...
        # yield to make this recognized as an async generator by type checkers
        if False:
            yield ""