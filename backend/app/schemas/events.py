"""Typed event shapes for the streaming chat endpoint.

SSE is a text-based protocol; each event is a small JSON object. Having
typed models on the backend means we can't accidentally send malformed
events, and the frontend (in TypeScript) can mirror these shapes
verbatim for end-to-end type safety.
"""
from typing import Literal

from pydantic import BaseModel


class TokenEvent(BaseModel):
    """A single content chunk from the LLM stream."""

    type: Literal["token"] = "token"
    content: str


class ProfileEvent(BaseModel):
    """Snapshot of the lead profile — emitted after extraction.

    Lets the frontend's debug panel update live as variables are collected.
    """

    type: Literal["profile"] = "profile"
    business_segment: str | None = None
    annual_usage_mwh: float | None = None
    contract_status: str | None = None
    building_age_years: int | None = None
    square_footage: int | None = None
    usage_was_estimated: bool = False


class TierEvent(BaseModel):
    """Emitted when qualification completes."""

    type: Literal["tier"] = "tier"
    tier: str
    matched_rule: str


class DoneEvent(BaseModel):
    """Sentinel marking the end of the stream.

    Frontend closes the EventSource cleanly when it sees this.
    """

    type: Literal["done"] = "done"


class ErrorEvent(BaseModel):
    """Something went wrong mid-stream."""

    type: Literal["error"] = "error"
    message: str