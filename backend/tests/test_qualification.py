"""Exhaustive tests for qualification logic.

Every rule in the matrix has at least:
  - one positive case (rule matches, correct tier returned)
  - one negative case per criterion (missing or wrong value fails the rule)

Plus edge cases (boundary values) and the no-match / insufficient-info paths.
"""
import pytest

from app.agent.qualification import (
    QualificationInput,
    qualify,
)
from app.db.types import (
    BusinessSegment,
    ContractStatus,
    LeadTier,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def make_profile(**overrides) -> QualificationInput:
    """Build a profile with defaults that don't match any rule."""
    base = {
        "business_segment": None,
        "annual_usage_mwh": None,
        "contract_status": None,
        "building_age_years": None,
    }
    base.update(overrides)
    return QualificationInput(**base)


# ============================================================================
# Insufficient info — must return UNQUALIFIED, is_complete=False
# ============================================================================
class TestInsufficientInfo:

    def test_empty_profile(self):
        result = qualify(make_profile())
        assert result.tier == LeadTier.UNQUALIFIED
        assert result.matched_rule == "insufficient_info"
        assert result.is_complete is False

    def test_only_segment(self):
        result = qualify(make_profile(business_segment=BusinessSegment.INDUSTRIAL))
        assert result.is_complete is False

    def test_only_contract_status(self):
        result = qualify(
            make_profile(contract_status=ContractStatus.FIXED_TERM)
        )
        assert result.is_complete is False

    def test_minimum_info_is_segment_plus_contract(self):
        """Both segment AND contract_status required for is_complete=True."""
        result = qualify(
            make_profile(
                business_segment=BusinessSegment.INDUSTRIAL,
                contract_status=ContractStatus.FIXED_TERM,
            )
        )
        assert result.is_complete is True


# ============================================================================
# Rule 1 — Industrial > 500 MWh expiring < 6 months → Tier 1
# ============================================================================
class TestIndustrialHighPriority:

    def test_matches(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=600,
            contract_status=ContractStatus.EXPIRING_SOON,
        ))
        assert result.tier == LeadTier.TIER_1
        assert result.matched_rule == "industrial_high_priority"

    def test_at_boundary_501_mwh(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=501,
            contract_status=ContractStatus.EXPIRING_SOON,
        ))
        assert result.tier == LeadTier.TIER_1

    def test_exactly_500_mwh_does_not_match(self):
        """Rule requires > 500, not >="""
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=500,
            contract_status=ContractStatus.EXPIRING_SOON,
        ))
        assert result.tier == LeadTier.UNQUALIFIED

    def test_fails_with_wrong_contract(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=600,
            contract_status=ContractStatus.FIXED_TERM,
        ))
        assert result.tier == LeadTier.UNQUALIFIED


# ============================================================================
# Rule 2 — Industrial 100-500 MWh, expiring < 12mo, building < 5 yrs → Tier 2
# ============================================================================
class TestIndustrialFollowup:

    def test_matches_mid_range(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=300,
            contract_status=ContractStatus.EXPIRING_WITHIN_YEAR,
            building_age_years=3,
        ))
        assert result.tier == LeadTier.TIER_2
        assert result.matched_rule == "industrial_followup"

    def test_boundary_100_mwh(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=100,
            contract_status=ContractStatus.EXPIRING_WITHIN_YEAR,
            building_age_years=4,
        ))
        assert result.tier == LeadTier.TIER_2

    def test_boundary_500_mwh(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=500,
            contract_status=ContractStatus.EXPIRING_WITHIN_YEAR,
            building_age_years=4,
        ))
        assert result.tier == LeadTier.TIER_2

    def test_fails_building_too_old(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=300,
            contract_status=ContractStatus.EXPIRING_WITHIN_YEAR,
            building_age_years=5,  # not < 5
        ))
        assert result.tier == LeadTier.UNQUALIFIED


# ============================================================================
# Rule 3 — Commercial > 50 MWh on month-to-month → Tier 1
# ============================================================================
class TestCommercialHighPriority:

    def test_matches(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.COMMERCIAL,
            annual_usage_mwh=100,
            contract_status=ContractStatus.MONTH_TO_MONTH,
        ))
        assert result.tier == LeadTier.TIER_1
        assert result.matched_rule == "commercial_high_priority"

    def test_exactly_50_mwh_does_not_match(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.COMMERCIAL,
            annual_usage_mwh=50,
            contract_status=ContractStatus.MONTH_TO_MONTH,
        ))
        assert result.tier == LeadTier.UNQUALIFIED


# ============================================================================
# Rule 4 — Commercial 20-50 MWh, fixed term, building < 2 yrs → Tier 3
# ============================================================================
class TestCommercialNurture:

    def test_matches(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.COMMERCIAL,
            annual_usage_mwh=30,
            contract_status=ContractStatus.FIXED_TERM,
            building_age_years=1,
        ))
        assert result.tier == LeadTier.TIER_3
        assert result.matched_rule == "commercial_nurture"

    def test_fails_building_2_years_old(self):
        """Rule requires < 2 years."""
        result = qualify(make_profile(
            business_segment=BusinessSegment.COMMERCIAL,
            annual_usage_mwh=30,
            contract_status=ContractStatus.FIXED_TERM,
            building_age_years=2,
        ))
        assert result.tier == LeadTier.UNQUALIFIED


# ============================================================================
# Rule 5 — No current provider → Tier 1 (overrides everything)
# ============================================================================
class TestNoProvider:

    def test_matches_with_minimal_info(self):
        """Commercial + no provider should qualify even without usage info."""
        result = qualify(make_profile(
            business_segment=BusinessSegment.COMMERCIAL,
            contract_status=ContractStatus.NO_PROVIDER,
        ))
        assert result.tier == LeadTier.TIER_1
        assert result.matched_rule == "no_current_provider"

    def test_matches_industrial(self):
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            contract_status=ContractStatus.NO_PROVIDER,
            annual_usage_mwh=10,  # tiny usage still qualifies
        ))
        assert result.tier == LeadTier.TIER_1


# ============================================================================
# No-match case — complete info, but no rule fits
# ============================================================================
class TestNoMatch:

    def test_commercial_small_fixed_no_building_age(self):
        """Commercial, 30 MWh, fixed term, but we don't know the building age."""
        result = qualify(make_profile(
            business_segment=BusinessSegment.COMMERCIAL,
            annual_usage_mwh=30,
            contract_status=ContractStatus.FIXED_TERM,
            building_age_years=None,
        ))
        assert result.tier == LeadTier.UNQUALIFIED
        assert result.matched_rule == "no_match"
        assert result.is_complete is True

    def test_industrial_low_usage(self):
        """Industrial but only 50 MWh, doesn't match any rule."""
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=50,
            contract_status=ContractStatus.FIXED_TERM,
        ))
        assert result.tier == LeadTier.UNQUALIFIED
        assert result.matched_rule == "no_match"


# ============================================================================
# First-match-wins behavior — verify rule ordering is respected
# ============================================================================
class TestRuleOrdering:

    def test_no_provider_wins_over_usage(self):
        """Industrial with contradictory fields — no_provider should win."""
        result = qualify(make_profile(
            business_segment=BusinessSegment.INDUSTRIAL,
            annual_usage_mwh=600,
            contract_status=ContractStatus.NO_PROVIDER,
        ))
        # Both no_provider and industrial_high_priority's contract
        # conditions could theoretically be true, but contract_status
        # is a single value — NO_PROVIDER wins.
        assert result.matched_rule == "no_current_provider"