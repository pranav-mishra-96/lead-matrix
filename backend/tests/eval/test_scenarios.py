"""Pytest runner for YAML-driven agent evaluation scenarios.

Each scenario in scenarios.yaml becomes one parametrized test case.
The runner drives a minimal version of the turn pipeline using a
FakeLLMClient, asserting tier decisions and profile state.

No database, no HTTP, no real LLM — all in-memory.
"""
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.agent.estimation import estimate_annual_usage_mwh
from app.agent.prompts import (
    build_conversation_messages,
    build_extraction_messages,
)
from app.agent.qualification import QualificationInput, qualify
from app.db.types import BusinessSegment, ContractStatus, LeadTier
from app.llm.interface import ChatMessage
from tests.eval.fake_llm import FakeLLMClient


SCENARIOS_PATH = Path(__file__).parent / "scenarios.yaml"


def load_scenarios() -> list[dict[str, Any]]:
    with open(SCENARIOS_PATH) as f:
        return yaml.safe_load(f)


# ----------------------------------------------------------------------------
# The in-memory turn runner — replicates the streaming runner's logic
# without any DB writes, so scenarios run at pure-Python speed.
# ----------------------------------------------------------------------------
class InMemoryProfile:
    """Drop-in replacement for the ORM LeadProfile — just fields."""

    def __init__(self):
        self.business_segment: BusinessSegment | None = None
        self.annual_usage_mwh: float | None = None
        self.contract_status: ContractStatus | None = None
        self.building_age_years: int | None = None
        self.square_footage: int | None = None
        self.usage_was_estimated: bool = False

    def apply(self, fields: dict) -> None:
        if "business_segment" in fields:
            try:
                self.business_segment = BusinessSegment(fields["business_segment"])
            except ValueError:
                pass
        if "contract_status" in fields:
            try:
                self.contract_status = ContractStatus(fields["contract_status"])
            except ValueError:
                pass
        if "annual_usage_mwh" in fields:
            self.annual_usage_mwh = float(fields["annual_usage_mwh"])
        if "building_age_years" in fields:
            self.building_age_years = int(fields["building_age_years"])
        if "square_footage" in fields:
            self.square_footage = int(fields["square_footage"])


async def run_scenario(scenario: dict) -> dict:
    """Run one scenario end-to-end, returning the final state."""
    fake = FakeLLMClient()
    profile = InMemoryProfile()
    history: list[dict] = []

    final_qr = None

    for turn in scenario["turns"]:
        # Queue the scripted extraction + conversational reply for this turn
        fake.queue_extraction(turn.get("extraction", {}))
        fake.queue_response(turn.get("assistant_reply", "[canned]"))

        user_message = turn["user"]

        # ------- Extraction call -------
        extract_messages = build_extraction_messages(history, user_message)
        extract_response = await fake.complete(
            messages=[ChatMessage(**m) for m in extract_messages],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        import json
        extracted = json.loads(extract_response.content)
        user_said_dont_know = extracted.pop("user_said_dont_know", False) is True
        profile.apply(extracted)

        # ------- Estimation fallback -------
        if (
            profile.square_footage
            and profile.business_segment
            and profile.annual_usage_mwh is None
        ):
            estimated = estimate_annual_usage_mwh(
                profile.square_footage, profile.business_segment,
            )
            profile.annual_usage_mwh = estimated
            profile.usage_was_estimated = True

        # ------- Qualification -------
        qr = qualify(QualificationInput(
            business_segment=profile.business_segment,
            annual_usage_mwh=profile.annual_usage_mwh,
            contract_status=profile.contract_status,
            building_age_years=profile.building_age_years,
        ))
        final_qr = qr

        # ------- Conversational response (canned, we ignore it) -------
        convo_messages = build_conversation_messages(
            history=history,
            user_message=user_message,
            next_question_hint="whatever",
            tier_announcement=None,
        )
        convo_response = await fake.complete(
            messages=[ChatMessage(**m) for m in convo_messages],
            temperature=0.7,
        )

        # Update history for next turn
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": convo_response.content})

    return {
        "qr": final_qr,
        "profile": profile,
        "fake_calls": fake.calls,
    }


# ----------------------------------------------------------------------------
# The actual test — pytest.parametrize generates one test per scenario
# ----------------------------------------------------------------------------
SCENARIOS = load_scenarios()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    SCENARIOS,
    ids=[s["name"] for s in SCENARIOS],
)
async def test_scenario(scenario: dict):
    """Run a scripted scenario and assert the final state."""
    result = await run_scenario(scenario)
    qr = result["qr"]
    profile = result["profile"]
    expected = scenario["expect"]

    # --- Tier ---
    assert qr is not None, "Qualification must have run"
    expected_tier = LeadTier(expected["tier"])
    assert qr.tier == expected_tier, (
        f"{scenario['name']}: expected tier={expected_tier.value}, "
        f"got {qr.tier.value} (rule={qr.matched_rule})"
    )

    # --- Matched rule ---
    assert qr.matched_rule == expected["rule"], (
        f"{scenario['name']}: expected rule={expected['rule']}, "
        f"got {qr.matched_rule}"
    )

    # --- is_complete (defaults to True if not specified) ---
    expected_complete = expected.get("complete", True)
    assert qr.is_complete == expected_complete, (
        f"{scenario['name']}: expected is_complete={expected_complete}, "
        f"got {qr.is_complete}"
    )

    # --- Optional profile assertions ---
    if "profile" in expected:
        for field, expected_value in expected["profile"].items():
            actual = getattr(profile, field)
            assert actual == expected_value, (
                f"{scenario['name']}: profile.{field} expected {expected_value}, "
                f"got {actual}"
            )