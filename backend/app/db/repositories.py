"""Repository functions — thin wrappers around common DB operations.

Each function takes an AsyncSession as first argument (injected from the
FastAPI dependency) and returns either ORM objects or plain primitives.

Routes should use these functions instead of writing SQL inline. This
keeps query logic centralized and testable.
"""
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    AgentTrace,
    Conversation,
    LeadProfile,
    Message,
    QualificationEvent,
)
from app.db.types import (
    BusinessSegment,
    ContractStatus,
    ConversationStatus,
    EventType,
    LeadTier,
    MessageRole,
)


# ============================================================================
# Conversations
# ============================================================================
async def create_conversation(session: AsyncSession) -> Conversation:
    """Start a new conversation in ACTIVE state.

    Also creates an empty LeadProfile linked to it — every conversation
    has exactly one, and creating it eagerly simplifies downstream code
    that can assume `conversation.lead_profile` is never None.
    """
    conversation = Conversation(status=ConversationStatus.ACTIVE)
    session.add(conversation)
    await session.flush()  # assign id without committing

    profile = LeadProfile(conversation_id=conversation.id)
    session.add(profile)
    await session.flush()

    return conversation


async def get_conversation(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> Conversation | None:
    """Fetch a conversation by id, eagerly loading messages + profile."""
    stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(
            selectinload(Conversation.messages),
            selectinload(Conversation.lead_profile),
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_conversation_status(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    status: ConversationStatus,
    final_tier: LeadTier | None = None,
) -> None:
    """Mark a conversation qualified/abandoned and optionally set tier."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        return
    conversation.status = status
    if final_tier is not None:
        conversation.final_tier = final_tier


async def update_current_step(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    step: str,
) -> None:
    """Record which agent node is currently executing."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is not None:
        conversation.current_step = step


# ============================================================================
# Messages
# ============================================================================
async def save_message(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
) -> Message:
    """Persist a user/assistant/system message."""
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
    )
    session.add(message)
    await session.flush()
    return message


async def list_messages(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> Sequence[Message]:
    """Return all messages for a conversation, oldest first."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ============================================================================
# Lead profiles
# ============================================================================
async def get_lead_profile(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> LeadProfile | None:
    """Fetch the profile for a conversation."""
    stmt = select(LeadProfile).where(
        LeadProfile.conversation_id == conversation_id
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_lead_profile(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,  # force keyword-only — prevents positional-arg ordering mistakes
    business_segment: BusinessSegment | None = None,
    annual_usage_mwh: float | None = None,
    contract_status: ContractStatus | None = None,
    building_age_years: int | None = None,
    square_footage: int | None = None,
    company_name: str | None = None,
    contact_name: str | None = None,
    usage_was_estimated: bool | None = None,
) -> LeadProfile | None:
    """Update any subset of profile fields. None values leave existing untouched.

    The keyword-only enforcement (after *) means callers must write:
        update_lead_profile(session, conv_id, business_segment=...)
    not:
        update_lead_profile(session, conv_id, "industrial")
    Prevents a whole class of "wrong argument slot" bugs.
    """
    profile = await get_lead_profile(session, conversation_id)
    if profile is None:
        return None

    if business_segment is not None:
        profile.business_segment = business_segment
    if annual_usage_mwh is not None:
        profile.annual_usage_mwh = annual_usage_mwh
    if contract_status is not None:
        profile.contract_status = contract_status
    if building_age_years is not None:
        profile.building_age_years = building_age_years
    if square_footage is not None:
        profile.square_footage = square_footage
    if company_name is not None:
        profile.company_name = company_name
    if contact_name is not None:
        profile.contact_name = contact_name
    if usage_was_estimated is not None:
        profile.usage_was_estimated = usage_was_estimated

    return profile


# ============================================================================
# Qualification events
# ============================================================================
async def record_event(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    event_type: EventType,
    payload: dict,
) -> QualificationEvent:
    """Append an event to the audit log."""
    event = QualificationEvent(
        conversation_id=conversation_id,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> Sequence[QualificationEvent]:
    """Return events in chronological order."""
    stmt = (
        select(QualificationEvent)
        .where(QualificationEvent.conversation_id == conversation_id)
        .order_by(QualificationEvent.created_at)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ============================================================================
# Agent traces
# ============================================================================
async def record_trace(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    node_name: str | None,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int | None,
    request_payload: dict | None,
    response_payload: dict | None,
) -> AgentTrace:
    """Log a single LLM call for observability."""
    trace = AgentTrace(
        conversation_id=conversation_id,
        node_name=node_name,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        request_payload=request_payload,
        response_payload=response_payload,
    )
    session.add(trace)
    await session.flush()
    return trace