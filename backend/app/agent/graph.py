"""Compile the LangGraph state machine for the qualification agent."""
import uuid
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.nodes import (
    NodeContext,
    decide_node,
    estimate_usage_node,
    extract_node,
    respond_node,
)
from app.agent.state import AgentState
from app.llm.traced import TracedLLMClient


def _should_estimate(state: AgentState) -> str:
    """After extract: do we need to run the estimation node?"""
    has_sqft = state.get("square_footage") is not None
    has_segment = state.get("business_segment") is not None
    has_usage = state.get("annual_usage_mwh") is not None
    if has_sqft and has_segment and not has_usage:
        return "estimate"
    return "decide"


def build_graph(
    session: AsyncSession,
    llm: TracedLLMClient,
    conversation_id: uuid.UUID,
) -> Any:
    """Build and compile the agent graph.

    Each node gets a NodeContext (session, llm, conversation_id) via
    functools.partial — LangGraph nodes expect a (state) -> dict signature,
    so we bind the context into the function.
    """
    ctx = NodeContext(session=session, llm=llm, conversation_id=conversation_id)

    graph = StateGraph(AgentState)

    # Register nodes, binding ctx into each via partial
    graph.add_node("extract", partial(extract_node, ctx=ctx))
    graph.add_node("estimate", partial(estimate_usage_node, ctx=ctx))
    graph.add_node("decide", partial(decide_node, ctx=ctx))
    graph.add_node("respond", partial(respond_node, ctx=ctx))

    # Edges — flow of control
    graph.add_edge(START, "extract")
    graph.add_conditional_edges(
        "extract",
        _should_estimate,
        {"estimate": "estimate", "decide": "decide"},
    )
    graph.add_edge("estimate", "decide")
    graph.add_edge("decide", "respond")
    graph.add_edge("respond", END)

    return graph.compile()