"""High-level runner — invoke the agent for one turn."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_graph
from app.agent.state import AgentState
from app.db import repositories
from app.db.types import ConversationStatus, MessageRole
from app.llm.factory import get_llm_client
from app.llm.traced import TracedLLMClient
from app.observability.logging import get_logger

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

    # If qualification completed, mark the conversation closed
    if final_state.get("final_tier") is not None:
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
            if final_state.get("final_tier") is not None
            else None
        ),
    }