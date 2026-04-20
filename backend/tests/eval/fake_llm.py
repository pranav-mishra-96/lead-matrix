"""FakeLLMClient — a scripted LLM for deterministic evaluation.

Satisfies the LLMClient Protocol by matching method signatures. Each
call pops the next scripted response from an internal queue.

Two kinds of scripted responses:
  - extraction: dict of fields to pretend were extracted (JSON-encoded)
  - conversation: plain text the 'assistant' would say

The test scenarios only care about extraction correctness and
tier decisions. Conversation text is mostly ignored in assertions,
so we return a canned placeholder string.
"""
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from app.llm.interface import ChatMessage, LLMResponse, LLMUsage


class FakeLLMClient:
    """LLMClient implementation that returns scripted responses.

    Usage:
        fake = FakeLLMClient(model="fake-gpt")
        fake.queue_extraction({"business_segment": "industrial"})
        fake.queue_response("Got it, industrial.")
    """

    def __init__(self, model: str = "fake-gpt-4o-mini"):
        self.model = model
        # Two separate queues because a single turn calls complete() twice:
        # once for extraction, once for the conversational response.
        self._extractions: deque[dict] = deque()
        self._responses: deque[str] = deque()
        # Record of all calls for post-test inspection
        self.calls: list[dict[str, Any]] = []

    def queue_extraction(self, fields: dict) -> None:
        """Queue the next extraction response."""
        self._extractions.append(fields)

    def queue_response(self, content: str = "[canned reply]") -> None:
        """Queue the next conversational response."""
        self._responses.append(content)

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append({
            "kind": "complete",
            "messages": [m.model_dump() for m in messages],
            "response_format": response_format,
        })

        # If response_format asked for JSON, it's an extraction call.
        # Otherwise it's a conversational response.
        if response_format and response_format.get("type") == "json_object":
            if not self._extractions:
                raise RuntimeError(
                    "FakeLLMClient: no extraction queued, but one was requested"
                )
            fields = self._extractions.popleft()
            content = json.dumps(fields)
        else:
            if not self._responses:
                # Non-streaming path hits this too. Default to generic reply
                # rather than failing — the scenarios assert on tier/profile,
                # not on the exact assistant text.
                content = "[canned assistant reply]"
            else:
                content = self._responses.popleft()

        return LLMResponse(
            content=content,
            model=self.model,
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            raw={"choices": [{"message": {"content": content}}]},
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streaming — yield the scripted response char by char."""
        self.calls.append({
            "kind": "stream",
            "messages": [m.model_dump() for m in messages],
        })
        content = self._responses.popleft() if self._responses else "[canned]"
        for ch in content:
            yield ch