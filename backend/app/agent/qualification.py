"""Pure qualification logic — maps a LeadProfile to a LeadTier.

ZERO LLM calls. This function is fully deterministic:
    qualify(same_profile) == qualify(same_profile)    # always

Keeping this logic separate from the LLM has three big wins:
  1. Reproducibility — tier decisions can be audited and replayed
  2. Testability — thousands of scenarios run in milliseconds, no cost
  3. Clarity — the rules of the business are legible as code

The agent (see app/agent/graph.py) is responsible for collecting the
variables via conversation. Once collected, the resulting LeadProfile
is handed to this function for the actual decision.
"""
from dataclasses import dataclass
from typing import Literal

from app.db.types import (
    BusinessSegment,
    ContractStatus,
    LeadTier,
)


# ============================================================================
# Input & output types
# ============================================================================
@dataclass(frozen=True)
class QualificationInput:
    """Plain dataclass holding the fields qualify() needs.

    We use a dataclass instead of the ORM LeadProfile model because:
      - qualification has no business being coupled to the DB layer
      - frozen=True makes the input immutable (no accidental mutation)
      - tests can construct inputs without a DB session

    The caller (agent or route handler) converts from LeadProfile to
    QualificationInput at the boundary.
    """

    business_segment: BusinessSegment | None
    annual_usage_mwh: float | None
    contract_status: ContractStatus | None
    building_age_years: int | None


@dataclass(frozen=True)
class QualificationResult:
    """What qualify() returns.

    Not just the tier — also the rule that matched (for audit logging),
    and whether the profile had enough info to decide at all.
    """

    tier: LeadTier
    matched_rule: str          # human-readable identifier of the rule
    is_complete: bool          # False if required fields were missing


# ============================================================================
# Rule predicates — each rule is a named function
# ============================================================================
def _is_industrial_high_priority(p: QualificationInput) -> bool:
    """Industrial > 500 MWh expiring < 6 months → Tier 1."""
    return (
        p.business_segment == BusinessSegment.INDUSTRIAL
        and p.annual_usage_mwh is not None
        and p.annual_usage_mwh > 500
        and p.contract_status == ContractStatus.EXPIRING_SOON
    )


def _is_industrial_followup(p: QualificationInput) -> bool:
    """Industrial 100-500 MWh, expiring < 12mo, building < 5 yrs → Tier 2."""
    return (
        p.business_segment == BusinessSegment.INDUSTRIAL
        and p.annual_usage_mwh is not None
        and 100 <= p.annual_usage_mwh <= 500
        and p.contract_status == ContractStatus.EXPIRING_WITHIN_YEAR
        and p.building_age_years is not None
        and p.building_age_years < 5
    )


def _is_commercial_high_priority(p: QualificationInput) -> bool:
    """Commercial > 50 MWh on month-to-month → Tier 1."""
    return (
        p.business_segment == BusinessSegment.COMMERCIAL
        and p.annual_usage_mwh is not None
        and p.annual_usage_mwh > 50
        and p.contract_status == ContractStatus.MONTH_TO_MONTH
    )


def _is_commercial_nurture(p: QualificationInput) -> bool:
    """Commercial 20-50 MWh, fixed term, building < 2 yrs → Tier 3."""
    return (
        p.business_segment == BusinessSegment.COMMERCIAL
        and p.annual_usage_mwh is not None
        and 20 <= p.annual_usage_mwh <= 50
        and p.contract_status == ContractStatus.FIXED_TERM
        and p.building_age_years is not None
        and p.building_age_years < 2
    )


def _has_no_provider(p: QualificationInput) -> bool:
    """Any business, any usage, no current provider → Tier 1."""
    return p.contract_status == ContractStatus.NO_PROVIDER


# ============================================================================
# Completeness check — do we have enough to decide?
# ============================================================================
def _has_minimum_info(p: QualificationInput) -> bool:
    """A profile is complete enough if we have segment + contract_status.

    Usage and building_age are only required by specific rules — if
    contract_status is NO_PROVIDER for example, we can decide Tier 1
    with nothing else.
    """
    return (
        p.business_segment is not None
        and p.contract_status is not None
    )


# ============================================================================
# Public API
# ============================================================================
# The rule list is evaluated in order. First match wins.
# Named tuples keep the mapping between predicate, tier, and rule-id visible.
_RULES: list[tuple[str, LeadTier, object]] = [
    # (rule_name, tier, predicate_function)
    ("no_current_provider", LeadTier.TIER_1, _has_no_provider),
    ("industrial_high_priority", LeadTier.TIER_1, _is_industrial_high_priority),
    ("commercial_high_priority", LeadTier.TIER_1, _is_commercial_high_priority),
    ("industrial_followup", LeadTier.TIER_2, _is_industrial_followup),
    ("commercial_nurture", LeadTier.TIER_3, _is_commercial_nurture),
]


def qualify(profile: QualificationInput) -> QualificationResult:
    """Evaluate rules in order and return the first match.

    If no rule matches, returns UNQUALIFIED with the "no_match" rule-id.
    If the profile lacks minimum info, returns UNQUALIFIED with
    "insufficient_info" so callers can distinguish "we decided they
    don't qualify" from "we don't have enough to decide yet."
    """
    if not _has_minimum_info(profile):
        return QualificationResult(
            tier=LeadTier.UNQUALIFIED,
            matched_rule="insufficient_info",
            is_complete=False,
        )

    for rule_name, tier, predicate in _RULES:
        if predicate(profile):  # type: ignore[operator]
            return QualificationResult(
                tier=tier,
                matched_rule=rule_name,
                is_complete=True,
            )

    return QualificationResult(
        tier=LeadTier.UNQUALIFIED,
        matched_rule="no_match",
        is_complete=True,
    )


# ============================================================================
# Helper — convert from ORM LeadProfile to QualificationInput
# ============================================================================
def from_lead_profile(
    business_segment: BusinessSegment | None,
    annual_usage_mwh: float | None,
    contract_status: ContractStatus | None,
    building_age_years: int | None,
) -> QualificationInput:
    """Boundary helper — keeps qualify() ignorant of SQLAlchemy.

    Callers pull fields off the ORM model, pass them here.
    """
    return QualificationInput(
        business_segment=business_segment,
        annual_usage_mwh=annual_usage_mwh,
        contract_status=contract_status,
        building_age_years=building_age_years,
    )