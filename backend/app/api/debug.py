"""Temporary debugging endpoints — remove before production.

Exists to verify the session + repository plumbing works end-to-end
before we build the real chat API.
"""
import uuid

from app.llm.factory import get_llm_client
from app.llm.interface import ChatMessage
from app.llm.traced import TracedLLMClient


from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories
from app.db.session import get_db_session
from app.db.types import MessageRole

router = APIRouter(prefix="/debug", tags=["debug"])


class ConversationCreated(BaseModel):
    conversation_id: uuid.UUID


class MessagePosted(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str


@router.post(
    "/conversation",
    response_model=ConversationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_debug_conversation(
    session: AsyncSession = Depends(get_db_session),
) -> ConversationCreated:
    """Create an empty conversation and return its id."""
    conversation = await repositories.create_conversation(session)
    return ConversationCreated(conversation_id=conversation.id)


class SendMessageIn(BaseModel):
    content: str


@router.post(
    "/conversation/{conversation_id}/message",
    response_model=MessagePosted,
)
async def post_debug_message(
    conversation_id: uuid.UUID,
    payload: SendMessageIn,
    session: AsyncSession = Depends(get_db_session),
) -> MessagePosted:
    """Append a user message to a conversation."""
    conversation = await repositories.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    message = await repositories.save_message(
        session=session,
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=payload.content,
    )
    return MessagePosted(
        message_id=message.id,
        conversation_id=conversation_id,
        role=message.role.value,
        content=message.content,
    )

class EchoIn(BaseModel):
    prompt: str


class EchoOut(BaseModel):
    response: str
    latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None


@router.post(
    "/conversation/{conversation_id}/llm-echo",
    response_model=EchoOut,
)
async def llm_echo(
    conversation_id: uuid.UUID,
    payload: EchoIn,
    session: AsyncSession = Depends(get_db_session),
) -> EchoOut:
    """Send a prompt to the LLM and return the response.

    Uses the TracedLLMClient so this call also persists to agent_traces.
    Purely for sanity-checking the LLM plumbing.
    """
    conversation = await repositories.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    client = get_llm_client()
    traced = TracedLLMClient(client, session, conversation_id)

    response = await traced.complete(
        messages=[
            ChatMessage(role="system", content="You are a helpful assistant. Answer briefly."),
            ChatMessage(role="user", content=payload.prompt),
        ],
        node_name="debug_echo",
    )

    return EchoOut(
        response=response.content,
        latency_ms=None,  # trace row has this; don't double-track
        prompt_tokens=response.usage.prompt_tokens if response.usage else None,
        completion_tokens=response.usage.completion_tokens if response.usage else None,
    )