"""AgentState — the typed dict that flows through every graph node.

Each node receives the current state, returns updates. LangGraph merges
the returned dict into the state. Keeping state flat and serializable
means we can:
  - persist mid-conversation state if we ever need to
  - inspect it in the DB trace
  - drive the graph with synthetic inputs in tests
"""
import uuid
from typing import Annotated, TypedDict

from app.agent.qualification import QualificationResult
from app.db.types import (
    BusinessSegment,
    ContractStatus,
    LeadTier,
)


class AgentState(TypedDict, total=False):
    """Full conversation state for one turn.

    total=False = all keys are optional. Nodes set what they produce;
    missing keys are fine.
    """

    # Identity
    conversation_id: uuid.UUID
    user_message: str              # the incoming message this turn

    # Message history (for LLM context)
    history: list[dict]            # [{"role": "user", "content": "..."}, ...]

    # Collected profile variables
    business_segment: BusinessSegment | None
    annual_usage_mwh: float | None
    contract_status: ContractStatus | None
    building_age_years: int | None
    square_footage: int | None
    usage_was_estimated: bool

    # Extraction results (what this turn revealed)
    newly_extracted: dict          # fields we learned this turn
    user_said_dont_know: bool      # triggers fallback

    # Decision
    qualification: QualificationResult | None

    # Output
    assistant_message: str
    final_tier: LeadTier | None