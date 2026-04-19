"""OpenAI implementation of the LLMClient Protocol.

Uses the official openai Python SDK (async version). Handles:
  - streaming and non-streaming completions
  - structured output via response_format
  - automatic retry on transient errors (SDK handles this by default)
  - token accounting
"""
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.llm.interface import ChatMessage, LLMResponse, LLMUsage
from app.observability.logging import get_logger

log = get_logger(__name__)


class OpenAIClient:
    """Concrete LLMClient backed by the OpenAI API.

    Satisfies the LLMClient Protocol by virtue of matching method
    signatures — no inheritance required.
    """

    def __init__(self, api_key: str, model: str, timeout: float = 30.0):
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Single-shot completion — returns full response at once."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format

        completion: ChatCompletion = await self._client.chat.completions.create(**kwargs)

        choice = completion.choices[0]
        content = choice.message.content or ""

        usage: LLMUsage | None = None
        if completion.usage is not None:
            usage = LLMUsage(
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                total_tokens=completion.usage.total_tokens,
            )

        return LLMResponse(
            content=content,
            model=completion.model,
            usage=usage,
            raw=completion.model_dump(),
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streaming completion — yields content chunks as they arrive."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        stream = await self._client.chat.completions.create(**kwargs)

        async for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            if delta.content:
                yield delta.content