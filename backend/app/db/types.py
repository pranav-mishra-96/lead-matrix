"""Shared enum types used across multiple models.

Defined once here so both the ORM and any plain-SQL code reference
the same values. These become native PostgreSQL enum types in the
generated migration — the DB itself enforces valid values.
"""
import enum


class MessageRole(str, enum.Enum):
    """Role of a message in a conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationStatus(str, enum.Enum):
    """Lifecycle state of a conversation."""

    ACTIVE = "active"          # still collecting information
    QUALIFIED = "qualified"    # tier decision reached
    ABANDONED = "abandoned"    # user left without completing


class LeadTier(str, enum.Enum):
    """Qualification outcome."""

    TIER_1 = "tier_1"          # instant priority
    TIER_2 = "tier_2"          # follow-up
    TIER_3 = "tier_3"          # nurture
    UNQUALIFIED = "unqualified"


class BusinessSegment(str, enum.Enum):
    """First of the 7 qualification variables."""

    INDUSTRIAL = "industrial"
    COMMERCIAL = "commercial"


class ContractStatus(str, enum.Enum):
    """One of the 7 qualification variables."""

    EXPIRING_SOON = "expiring_soon"          # < 6 months
    EXPIRING_WITHIN_YEAR = "expiring_within_year"  # < 12 months
    MONTH_TO_MONTH = "month_to_month"
    FIXED_TERM = "fixed_term"
    NO_PROVIDER = "no_provider"


class EventType(str, enum.Enum):
    """Types of events we log during qualification."""

    VARIABLE_COLLECTED = "variable_collected"
    FALLBACK_TRIGGERED = "fallback_triggered"
    ESTIMATION_APPLIED = "estimation_applied"
    TIER_DETERMINED = "tier_determined"