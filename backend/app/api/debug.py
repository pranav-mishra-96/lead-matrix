"""Temporary debugging endpoints — remove before production.

Exists to verify the session + repository plumbing works end-to-end
before we build the real chat API.
"""
import uuid

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