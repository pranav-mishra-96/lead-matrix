"""Public chat API — the real endpoint the frontend will call."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import run_turn
from app.db import repositories
from app.db.session import get_db_session
from fastapi.responses import StreamingResponse
from app.agent.runner import run_turn_streaming


router = APIRouter(prefix="/chat", tags=["chat"])


class StartConversationOut(BaseModel):
    conversation_id: uuid.UUID
    assistant_message: str


class SendMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class SendMessageOut(BaseModel):
    assistant_message: str
    final_tier: str | None = None


@router.post(
    "/start",
    response_model=StartConversationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Begin a new qualification conversation",
)
async def start_conversation(
    session: AsyncSession = Depends(get_db_session),
) -> StartConversationOut:
    """Create a new conversation with an initial greeting."""
    conversation = await repositories.create_conversation(session)

    # Kick off with a simple greeting — no LLM call needed for the first turn.
    # Saves cost and guarantees a fast initial response.
    greeting = (
        "Hi! I'm here to help figure out the best energy plan for your business. "
        "To get started, could you tell me a bit about your operation — are you "
        "running an industrial facility or a commercial business?"
    )
    from app.db.types import MessageRole
    await repositories.save_message(
        session,
        conversation.id,
        role=MessageRole.ASSISTANT,
        content=greeting,
    )

    return StartConversationOut(
        conversation_id=conversation.id,
        assistant_message=greeting,
    )


@router.post(
    "/{conversation_id}/message",
    response_model=SendMessageOut,
    summary="Send a message and get the agent's response",
)
async def send_message(
    conversation_id: uuid.UUID,
    payload: SendMessageIn,
    session: AsyncSession = Depends(get_db_session),
) -> SendMessageOut:
    """Send a user message, run the agent, return the assistant reply."""
    conversation = await repositories.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    result = await run_turn(
        session=session,
        conversation_id=conversation_id,
        user_message=payload.content,
    )

    return SendMessageOut(
        assistant_message=result["assistant_message"],
        final_tier=result["final_tier"],
    )

@router.post(
    "/{conversation_id}/stream",
    summary="Send a message and stream the agent's response via SSE",
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-sent events stream",
        },
    },
)
async def stream_message(
    conversation_id: uuid.UUID,
    payload: SendMessageIn,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Stream the agent's response as Server-Sent Events.

    Event types (see app/schemas/events.py):
      - profile: snapshot of collected lead data
      - tier: final qualification outcome (only when decided)
      - token: content chunk from the LLM
      - done: end of stream
      - error: something went wrong

    Frontend uses EventSource to consume this.
    """
    conversation = await repositories.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    async def event_stream():
        try:
            async for sse_line in run_turn_streaming(
                session=session,
                conversation_id=conversation_id,
                user_message=payload.content,
            ):
                yield sse_line
        except Exception as exc:
            import json
            error_payload = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable buffering in nginx/proxies
        },
    )