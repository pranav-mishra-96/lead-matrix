"""Trace-logging wrapper around the LLM client.

Every call persists a row to agent_traces with:
  - prompt sent
  - full response
  - token counts
  - wall-clock latency
  - originating node (if provided)

This gives us an auditable log of every LLM interaction for a
conversation, which is what "observability of agent reasoning"
looks like in practice.
"""
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories
from app.llm.interface import ChatMessage, LLMClient, LLMResponse
from app.observability.logging import get_logger

log = get_logger(__name__)


class TracedLLMClient:
    """Decorator that adds trace logging to any LLMClient.

    Usage:
        base_client = get_llm_client()
        traced = TracedLLMClient(base_client, session, conversation_id)
        response = await traced.complete(messages, node_name="ask_segment")
    """

    def __init__(
        self,
        inner: LLMClient,
        session: AsyncSession,
        conversation_id: uuid.UUID,
    ):
        self._inner = inner
        self._session = session
        self._conversation_id = conversation_id
        self.model = inner.model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        node_name: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Wrap inner.complete() with persistence to agent_traces."""
        start = time.perf_counter()
        try:
            response = await self._inner.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            await repositories.record_trace(
                session=self._session,
                conversation_id=self._conversation_id,
                node_name=node_name,
                model=self._inner.model,
                prompt_tokens=None,
                completion_tokens=None,
                latency_ms=latency_ms,
                request_payload={
                    "messages": [m.model_dump() for m in messages],
                    "temperature": temperature,
                },
                response_payload={"error": str(exc)},
            )
            log.exception("llm_call_failed", node=node_name)
            raise

        latency_ms = int((time.perf_counter() - start) * 1000)

        await repositories.record_trace(
            session=self._session,
            conversation_id=self._conversation_id,
            node_name=node_name,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens if response.usage else None,
            completion_tokens=response.usage.completion_tokens if response.usage else None,
            latency_ms=latency_ms,
            request_payload={
                "messages": [m.model_dump() for m in messages],
                "temperature": temperature,
            },
            response_payload=response.raw,
        )

        log.info(
            "llm_call_completed",
            node=node_name,
            model=response.model,
            latency_ms=latency_ms,
            prompt_tokens=response.usage.prompt_tokens if response.usage else None,
            completion_tokens=response.usage.completion_tokens if response.usage else None,
        )

        return response

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        node_name: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Wrap inner.stream() with persistence of the accumulated response."""
        start = time.perf_counter()
        chunks: list[str] = []

        try:
            async for chunk in self._inner.stream(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                chunks.append(chunk)
                yield chunk
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            full_content = "".join(chunks)
            await repositories.record_trace(
                session=self._session,
                conversation_id=self._conversation_id,
                node_name=node_name,
                model=self._inner.model,
                prompt_tokens=None,  # streaming doesn't return token counts
                completion_tokens=None,
                latency_ms=latency_ms,
                request_payload={
                    "messages": [m.model_dump() for m in messages],
                    "temperature": temperature,
                    "streaming": True,
                },
                response_payload={"content": full_content},
            )
            log.info(
                "llm_stream_completed",
                node=node_name,
                latency_ms=latency_ms,
                chunk_count=len(chunks),
            )