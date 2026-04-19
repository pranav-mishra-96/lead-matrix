"""High-level runner — invoke the agent for one turn."""

import json

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_graph
from app.agent.state import AgentState
from app.db import repositories
from app.db.types import ConversationStatus, MessageRole
from app.llm.factory import get_llm_client
from app.llm.traced import TracedLLMClient
from app.observability.logging import get_logger


from collections.abc import AsyncIterator

from app.agent.estimation import estimate_annual_usage_mwh
from app.agent.prompts import build_conversation_messages, build_extraction_messages
from app.agent.qualification import QualificationInput, qualify
from app.db.types import EventType
from app.llm.interface import ChatMessage
from app.schemas.events import DoneEvent, ProfileEvent, TierEvent, TokenEvent


log = get_logger(__name__)


async def run_turn(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    user_message: str,
) -> dict:
    """Run one agent turn for the given user message.

    Returns a dict with assistant_message and optional final_tier.
    All persistence (messages, events, traces, profile updates) happens
    inside the graph nodes — this function only returns the user-facing result.
    """
    # Persist the user message first
    await repositories.save_message(
        session,
        conversation_id,
        role=MessageRole.USER,
        content=user_message,
    )

    # Load conversation + profile for current state
    conversation = await repositories.get_conversation(session, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation not found: {conversation_id}")
    profile = conversation.lead_profile

    # Build history from persisted messages (excluding the one we just added,
    # since user_message is passed separately into state)
    history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in conversation.messages[:-1]
    ]

    # Set up the graph
    llm = TracedLLMClient(
        inner=get_llm_client(),
        session=session,
        conversation_id=conversation_id,
    )
    graph = build_graph(session, llm, conversation_id)

    # Initial state — carry over what the profile already has
    initial_state: AgentState = {
        "conversation_id": conversation_id,
        "user_message": user_message,
        "history": history,
        "business_segment": profile.business_segment if profile else None,
        "annual_usage_mwh": (
            float(profile.annual_usage_mwh) if profile and profile.annual_usage_mwh else None
        ),
        "contract_status": profile.contract_status if profile else None,
        "building_age_years": profile.building_age_years if profile else None,
        "square_footage": profile.square_footage if profile else None,
        "usage_was_estimated": profile.usage_was_estimated if profile else False,
        "newly_extracted": {},
        "user_said_dont_know": False,
    }

    # Run the graph
    final_state = await graph.ainvoke(initial_state)

    # Only treat qualification as real if it's both present AND complete
    qr = final_state.get("qualification")
    is_truly_qualified = (
        qr is not None
        and qr.is_complete
        and final_state.get("final_tier") is not None
    )

    if is_truly_qualified:
        await repositories.update_conversation_status(
            session,
            conversation_id,
            status=ConversationStatus.QUALIFIED,
            final_tier=final_state["final_tier"],
        )
        log.info(
            "conversation_qualified",
            conversation_id=str(conversation_id),
            tier=final_state["final_tier"].value,
        )

    return {
        "assistant_message": final_state.get("assistant_message", ""),
        "final_tier": (
            final_state["final_tier"].value
            if is_truly_qualified
            else None
        ),
    }


async def run_turn_streaming(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    user_message: str,
) -> AsyncIterator[str]:
    """Run one agent turn and yield SSE-formatted event strings.

    Shape of the turn:
      1. Persist user message
      2. Extract structured fields (non-streamed LLM call)
      3. Emit profile snapshot event
      4. Apply estimation fallback if needed
      5. Run qualification
      6. Emit tier event if qualification completed
      7. Stream the conversational response (tokens flow live)
      8. Persist the accumulated assistant message
      9. Update conversation status if qualified
      10. Emit done event
    """
    # Step 1: persist user message
    await repositories.save_message(
        session, conversation_id, role=MessageRole.USER, content=user_message,
    )

    # Load current conversation + profile
    conversation = await repositories.get_conversation(session, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation not found: {conversation_id}")
    profile = conversation.lead_profile

    history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in conversation.messages[:-1]  # exclude the one we just saved
    ]

    llm = TracedLLMClient(
        inner=get_llm_client(),
        session=session,
        conversation_id=conversation_id,
    )

    # Step 2: extract structured fields
    extract_messages = build_extraction_messages(history, user_message)
    extract_response = await llm.complete(
        messages=[ChatMessage(**m) for m in extract_messages],
        node_name="extract",
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    extracted, user_said_dont_know = _parse_extraction(extract_response.content)
    if extracted:
        await repositories.update_lead_profile(
            session, conversation_id, **extracted,
        )
        await repositories.record_event(
            session, conversation_id,
            EventType.VARIABLE_COLLECTED,
            payload={
                k: (v.value if hasattr(v, "value") else v)
                for k, v in extracted.items()
            },
        )
        # Reload profile to get fresh values
        profile = await repositories.get_lead_profile(session, conversation_id)

    # Step 3: emit profile snapshot (even if nothing changed — idempotent)
    yield _sse(ProfileEvent(
        business_segment=profile.business_segment.value if profile and profile.business_segment else None,
        annual_usage_mwh=float(profile.annual_usage_mwh) if profile and profile.annual_usage_mwh else None,
        contract_status=profile.contract_status.value if profile and profile.contract_status else None,
        building_age_years=profile.building_age_years if profile else None,
        square_footage=profile.square_footage if profile else None,
        usage_was_estimated=profile.usage_was_estimated if profile else False,
    ))

    # Step 4: estimation fallback
    if (
        profile and profile.square_footage
        and profile.business_segment
        and not profile.annual_usage_mwh
    ):
        estimated = estimate_annual_usage_mwh(
            profile.square_footage, profile.business_segment,
        )
        await repositories.update_lead_profile(
            session, conversation_id,
            annual_usage_mwh=estimated,
            usage_was_estimated=True,
        )
        await repositories.record_event(
            session, conversation_id,
            EventType.ESTIMATION_APPLIED,
            payload={
                "square_footage": profile.square_footage,
                "segment": profile.business_segment.value,
                "estimated_mwh": estimated,
            },
        )
        profile = await repositories.get_lead_profile(session, conversation_id)
        # Re-emit profile with the estimate
        yield _sse(ProfileEvent(
            business_segment=profile.business_segment.value if profile.business_segment else None,
            annual_usage_mwh=float(profile.annual_usage_mwh) if profile.annual_usage_mwh else None,
            contract_status=profile.contract_status.value if profile.contract_status else None,
            building_age_years=profile.building_age_years,
            square_footage=profile.square_footage,
            usage_was_estimated=profile.usage_was_estimated,
        ))

    # Step 5: qualify
    qr = qualify(QualificationInput(
        business_segment=profile.business_segment if profile else None,
        annual_usage_mwh=float(profile.annual_usage_mwh) if profile and profile.annual_usage_mwh else None,
        contract_status=profile.contract_status if profile else None,
        building_age_years=profile.building_age_years if profile else None,
    ))

    # Step 6: if complete, record event and emit tier event
    if qr.is_complete:
        await repositories.record_event(
            session, conversation_id,
            EventType.TIER_DETERMINED,
            payload={"tier": qr.tier.value, "rule": qr.matched_rule},
        )
        yield _sse(TierEvent(tier=qr.tier.value, matched_rule=qr.matched_rule))

    # Step 7: stream the conversational response
    next_hint, tier_announcement = _build_response_hints(
        qr, user_said_dont_know, profile,
    )
    convo_messages = build_conversation_messages(
        history=history,
        user_message=user_message,
        next_question_hint=next_hint,
        tier_announcement=tier_announcement,
    )

    accumulated: list[str] = []
    async for chunk in llm.stream(
        messages=[ChatMessage(**m) for m in convo_messages],
        node_name="respond_stream",
        temperature=0.7,
    ):
        accumulated.append(chunk)
        yield _sse(TokenEvent(content=chunk))

    # Step 8: persist the accumulated assistant message
    full_message = "".join(accumulated)
    await repositories.save_message(
        session, conversation_id,
        role=MessageRole.ASSISTANT,
        content=full_message,
    )

    # Step 9: update conversation status if qualified
    if qr.is_complete:
        await repositories.update_conversation_status(
            session, conversation_id,
            status=ConversationStatus.QUALIFIED,
            final_tier=qr.tier,
        )

    # Step 10: done
    yield _sse(DoneEvent())


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _sse(event: BaseModel) -> str:
    """Format a Pydantic event as a single SSE message.

    SSE format: each message is `data: <payload>\\n\\n`. The double newline
    is the message boundary. JSON-encode our Pydantic events as the payload.
    """
    return f"data: {event.model_dump_json()}\n\n"


def _parse_extraction(content: str) -> tuple[dict, bool]:
    """Parse the extraction LLM's JSON response into (fields, said_dont_know)."""
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        log.warning("extraction_bad_json", content=content[:200])
        return {}, False

    user_said_dont_know = raw.pop("user_said_dont_know", False) is True

    coerced: dict = {}
    if "business_segment" in raw:
        try:
            from app.db.types import BusinessSegment
            coerced["business_segment"] = BusinessSegment(raw["business_segment"])
        except ValueError:
            pass
    if "contract_status" in raw:
        try:
            from app.db.types import ContractStatus
            coerced["contract_status"] = ContractStatus(raw["contract_status"])
        except ValueError:
            pass
    if "annual_usage_mwh" in raw and isinstance(raw["annual_usage_mwh"], (int, float)):
        coerced["annual_usage_mwh"] = float(raw["annual_usage_mwh"])
    for key in ("building_age_years", "square_footage"):
        if key in raw and isinstance(raw[key], (int, float)):
            coerced[key] = int(raw[key])

    return coerced, user_said_dont_know


def _build_response_hints(qr, user_said_dont_know, profile):
    """Same logic as respond_node, extracted so both streaming and non-streaming paths can use it."""
    from app.db.types import LeadTier

    if qr.is_complete:
        closing_instruction = (
            "This is the FINAL message of the conversation. "
            "Do NOT ask any follow-up questions. "
            "Do NOT offer additional help. "
            "End warmly in 1-2 sentences."
        )
        if qr.tier == LeadTier.TIER_1:
            return None, (
                "Tell the customer they're a high priority for us, "
                "thank them for the conversation, and let them know an "
                "account executive will reach out within one business day. "
                + closing_instruction
            )
        elif qr.tier == LeadTier.TIER_2:
            return None, (
                "Tell the customer they're a good fit for follow-up, thank "
                "them, and mention a specialist will reach out this week. "
                + closing_instruction
            )
        elif qr.tier == LeadTier.TIER_3:
            return None, (
                "Thank the customer warmly, mention we'll add them to our "
                "nurture list with relevant content as their needs evolve. "
                + closing_instruction
            )
        else:
            return None, (
                "Thank the customer for their time, and let them know we "
                "don't currently have an offer that fits their situation "
                "but they're welcome to reach back out later. "
                + closing_instruction
            )

    if user_said_dont_know and profile and not profile.annual_usage_mwh:
        return (
            "The user doesn't know their annual usage. Pivot gently by asking "
            "for their facility's square footage — tell them you can estimate "
            "usage from that."
        ), None

    # Next missing variable
    if profile is None or profile.business_segment is None:
        return "Ask whether their business is industrial or commercial.", None
    if profile.contract_status is None:
        return (
            "Ask about their current energy contract status — when it expires, "
            "or whether they have one at all."
        ), None
    if profile.annual_usage_mwh is None:
        return "Ask about their approximate annual energy usage in MWh.", None
    if profile.building_age_years is None:
        return "Ask how old their facility or building is.", None
    return "Gently re-engage the user and see if they have more details to share.", None