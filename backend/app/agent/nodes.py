"""Individual graph nodes.

Each node is an async function: (state) -> partial state updates.
LangGraph merges the returned dict into the working state.
"""
import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.estimation import estimate_annual_usage_mwh
from app.agent.prompts import (
    build_conversation_messages,
    build_extraction_messages,
)
from app.agent.qualification import (
    QualificationInput,
    qualify,
)
from app.agent.state import AgentState
from app.db import repositories
from app.db.types import (
    BusinessSegment,
    ContractStatus,
    EventType,
    LeadTier,
    MessageRole,
)
from app.llm.interface import ChatMessage
from app.llm.traced import TracedLLMClient
from app.observability.logging import get_logger

log = get_logger(__name__)


# ----------------------------------------------------------------------------
# Node context — dependencies each node needs
# ----------------------------------------------------------------------------
class NodeContext:
    """Bundle of dependencies passed to nodes via a closure.

    LangGraph nodes are plain functions of state, but our nodes need
    access to the DB session and LLM client. We wrap them in a closure
    via build_graph() — each node sees 'ctx' captured from the outer scope.
    """

    def __init__(
        self,
        session: AsyncSession,
        llm: TracedLLMClient,
        conversation_id: uuid.UUID,
    ):
        self.session = session
        self.llm = llm
        self.conversation_id = conversation_id


# ============================================================================
# Node 1 — Extract structured fields from user's message
# ============================================================================
async def extract_node(state: AgentState, ctx: NodeContext) -> dict[str, Any]:
    """Ask the LLM to pull structured data from the user's message."""
    messages = build_extraction_messages(
        history=state.get("history", []),
        user_message=state["user_message"],
    )

    response = await ctx.llm.complete(
        messages=[ChatMessage(**m) for m in messages],
        node_name="extract",
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    try:
        extracted = json.loads(response.content)
    except json.JSONDecodeError:
        log.warning("extract_node_bad_json", content=response.content[:200])
        extracted = {}

    # Coerce string enum values into our Python enums
    coerced: dict[str, Any] = {}
    if "business_segment" in extracted:
        try:
            coerced["business_segment"] = BusinessSegment(extracted["business_segment"])
        except ValueError:
            pass
    if "contract_status" in extracted:
        try:
            coerced["contract_status"] = ContractStatus(extracted["contract_status"])
        except ValueError:
            pass
    for key in ("annual_usage_mwh",):
        if key in extracted and isinstance(extracted[key], (int, float)):
            coerced[key] = float(extracted[key])
    for key in ("building_age_years", "square_footage"):
        if key in extracted and isinstance(extracted[key], (int, float)):
            coerced[key] = int(extracted[key])
    if extracted.get("user_said_dont_know") is True:
        coerced["user_said_dont_know"] = True

    # Persist what we learned
    if coerced:
        await repositories.update_lead_profile(
            ctx.session,
            ctx.conversation_id,
            **{k: v for k, v in coerced.items() if k != "user_said_dont_know"},
        )
        await repositories.record_event(
            ctx.session,
            ctx.conversation_id,
            EventType.VARIABLE_COLLECTED,
            payload={k: (v.value if hasattr(v, "value") else v) for k, v in coerced.items()},
        )

    # Merge newly extracted into state (alongside existing state)
    updates: dict[str, Any] = {"newly_extracted": coerced}
    updates.update(coerced)
    return updates


# ============================================================================
# Node 2 — Apply fallback: estimate usage from square footage
# ============================================================================
async def estimate_usage_node(state: AgentState, ctx: NodeContext) -> dict[str, Any]:
    """If we have square_footage and segment but no usage, estimate it."""
    sq_ft = state.get("square_footage")
    segment = state.get("business_segment")
    current_usage = state.get("annual_usage_mwh")

    if sq_ft is None or segment is None or current_usage is not None:
        return {}

    estimated_mwh = estimate_annual_usage_mwh(sq_ft, segment)

    await repositories.update_lead_profile(
        ctx.session,
        ctx.conversation_id,
        annual_usage_mwh=estimated_mwh,
        usage_was_estimated=True,
    )
    await repositories.record_event(
        ctx.session,
        ctx.conversation_id,
        EventType.ESTIMATION_APPLIED,
        payload={
            "square_footage": sq_ft,
            "segment": segment.value,
            "estimated_mwh": estimated_mwh,
        },
    )
    log.info(
        "usage_estimated",
        square_footage=sq_ft,
        segment=segment.value,
        estimated_mwh=estimated_mwh,
    )

    return {"annual_usage_mwh": estimated_mwh, "usage_was_estimated": True}


# ============================================================================
# Node 3 — Decide: can we qualify the lead yet?
# ============================================================================
async def decide_node(state: AgentState, ctx: NodeContext) -> dict[str, Any]:
    """Run pure qualification logic against current state."""
    result = qualify(QualificationInput(
        business_segment=state.get("business_segment"),
        annual_usage_mwh=state.get("annual_usage_mwh"),
        contract_status=state.get("contract_status"),
        building_age_years=state.get("building_age_years"),
    ))

    if result.is_complete:
        await repositories.record_event(
            ctx.session,
            ctx.conversation_id,
            EventType.TIER_DETERMINED,
            payload={"tier": result.tier.value, "rule": result.matched_rule},
        )

    return {"qualification": result}


# ============================================================================
# Node 4 — Respond: the conversational LLM turn
# ============================================================================
async def respond_node(state: AgentState, ctx: NodeContext) -> dict[str, Any]:
    """Generate the assistant's reply for this turn.

    Three scenarios, handled by different hints to the LLM:
      1. Qualification complete → announce the tier
      2. User said "I don't know" about usage → pivot to square footage
      3. Still missing info → ask the next logical question
    """
    qr = state.get("qualification")
    next_hint: str | None = None
    tier_announcement: str | None = None

    if qr is not None and qr.is_complete:
        # Case 1: we have a tier — announce it and END the conversation.
        # The 'DO NOT ask' instruction is critical; without it the LLM
        # tends to add a follow-up question out of helpfulness.
        closing_instruction = (
            "This is the FINAL message of the conversation. "
            "Do NOT ask any follow-up questions. "
            "Do NOT offer additional help. "
            "End warmly in 1-2 sentences."
        )
        if qr.tier == LeadTier.TIER_1:
            tier_announcement = (
                "Tell the customer they're a high priority for us, "
                "thank them for the conversation, and let them know an "
                "account executive will reach out within one business day. "
                + closing_instruction
            )
        elif qr.tier == LeadTier.TIER_2:
            tier_announcement = (
                "Tell the customer they're a good fit for follow-up, thank "
                "them, and mention a specialist will reach out this week. "
                + closing_instruction
            )
        elif qr.tier == LeadTier.TIER_3:
            tier_announcement = (
                "Thank the customer warmly, mention we'll add them to our "
                "nurture list with relevant content as their needs evolve. "
                + closing_instruction
            )
        else:
            tier_announcement = (
                "Thank the customer for their time, and let them know we "
                "don't currently have an offer that fits their situation "
                "but they're welcome to reach back out later. "
                + closing_instruction
            )
    elif state.get("user_said_dont_know") and state.get("annual_usage_mwh") is None:
        # Case 2: fallback
        next_hint = (
            "The user doesn't know their annual usage. Pivot gently by asking "
            "for their facility's square footage — tell them you can estimate "
            "usage from that."
        )
    else:
        # Case 3: next missing variable
        next_hint = _next_question_hint(state)

    messages = build_conversation_messages(
        history=state.get("history", []),
        user_message=state["user_message"],
        next_question_hint=next_hint,
        tier_announcement=tier_announcement,
    )

    response = await ctx.llm.complete(
        messages=[ChatMessage(**m) for m in messages],
        node_name="respond",
        temperature=0.7,
    )
    assistant_message = response.content.strip()

    # Persist the assistant message
    await repositories.save_message(
        ctx.session,
        ctx.conversation_id,
        role=MessageRole.ASSISTANT,
        content=assistant_message,
    )

    updates: dict[str, Any] = {"assistant_message": assistant_message}
    if qr is not None and qr.is_complete:
        updates["final_tier"] = qr.tier
    return updates


def _next_question_hint(state: AgentState) -> str:
    """Choose which variable to ask about next based on what's missing."""
    if state.get("business_segment") is None:
        return "Ask whether their business is industrial or commercial."
    if state.get("contract_status") is None:
        return (
            "Ask about their current energy contract status — when it expires, "
            "or whether they have one at all."
        )
    if state.get("annual_usage_mwh") is None:
        return "Ask about their approximate annual energy usage in MWh."
    if state.get("building_age_years") is None:
        return "Ask how old their facility or building is."
    return "Gently re-engage the user and see if they have more details to share."