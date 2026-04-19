"""ORM models for the Strategic Lead Matrix database.

All timestamps are timezone-aware (TIMESTAMPTZ). Primary keys are UUIDs.
Foreign keys cascade deletes so orphaned rows are impossible.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import (
    BusinessSegment,
    ContractStatus,
    ConversationStatus,
    EventType,
    LeadTier,
    MessageRole,
)

if TYPE_CHECKING:
    # Forward references only needed for type checkers
    pass


# ----------------------------------------------------------------------------
# Helper — a UUID column with sensible defaults
# ----------------------------------------------------------------------------
def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        server_default=func.now(),
        nullable=False,
    )


# ============================================================================
# Conversation — one row per chat session
# ============================================================================
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    status: Mapped[ConversationStatus] = mapped_column(
        PgEnum(ConversationStatus, name="conversation_status"),
        nullable=False,
        default=ConversationStatus.ACTIVE,
    )
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_tier: Mapped[LeadTier | None] = mapped_column(
        PgEnum(LeadTier, name="lead_tier"),
        nullable=True,
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    lead_profile: Mapped["LeadProfile | None"] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        uselist=False,
    )
    events: Mapped[list["QualificationEvent"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="QualificationEvent.created_at",
    )
    traces: Mapped[list["AgentTrace"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AgentTrace.created_at",
    )

    __table_args__ = (
        Index("ix_conversations_status_created_at", "status", "created_at"),
    )


# ============================================================================
# Message — one row per user or assistant message
# ============================================================================
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        PgEnum(MessageRole, name="message_role"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# ============================================================================
# LeadProfile — the 7 qualification variables for a single conversation
# ============================================================================
class LeadProfile(Base):
    __tablename__ = "lead_profiles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # one profile per conversation
    )

    # The 7 qualification variables — all nullable (fill in progressively)
    business_segment: Mapped[BusinessSegment | None] = mapped_column(
        PgEnum(BusinessSegment, name="business_segment"),
        nullable=True,
    )
    annual_usage_mwh: Mapped[float | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )
    contract_status: Mapped[ContractStatus | None] = mapped_column(
        PgEnum(ContractStatus, name="contract_status"),
        nullable=True,
    )
    building_age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    square_footage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Flag: did we estimate usage from square footage?
    usage_was_estimated: Mapped[bool] = mapped_column(default=False, nullable=False)

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="lead_profile")


# ============================================================================
# QualificationEvent — audit log of agent decisions
# ============================================================================
class QualificationEvent(Base):
    __tablename__ = "qualification_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[EventType] = mapped_column(
        PgEnum(EventType, name="event_type"),
        nullable=False,
    )
    # Free-form structured payload — variable collected, rule matched, etc.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()

    conversation: Mapped[Conversation] = relationship(back_populates="events")


# ============================================================================
# AgentTrace — one row per LLM call for cost/latency observability
# ============================================================================
class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Store full prompt/response for replay + debugging
    request_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    conversation: Mapped[Conversation] = relationship(back_populates="traces")