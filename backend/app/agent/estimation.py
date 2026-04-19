"""Estimate annual energy usage from building square footage.

This is the "Logic Fallback" from the challenge:
  - User doesn't know their annual usage
  - We ask for square footage instead
  - We estimate usage as sq_ft × energy_intensity

Industry rule-of-thumb values from EIA's Commercial Buildings Energy
Consumption Survey (CBECS):
  - Commercial office: ~12-18 kWh per sq ft per year
  - Industrial/manufacturing: ~25-40 kWh per sq ft per year

We use mid-range values. This is deliberately conservative — good
enough to place the lead in the right bucket, not meant as a final
billing estimate.
"""
from app.db.types import BusinessSegment


# kWh per square foot per year
_ENERGY_INTENSITY_KWH_PER_SQFT: dict[BusinessSegment, float] = {
    BusinessSegment.COMMERCIAL: 15.0,
    BusinessSegment.INDUSTRIAL: 30.0,
}


def estimate_annual_usage_mwh(
    square_footage: int,
    business_segment: BusinessSegment,
) -> float:
    """Return estimated annual usage in MWh.

    MWh = sq_ft × (kWh/sq_ft/yr) ÷ 1000
    """
    intensity_kwh = _ENERGY_INTENSITY_KWH_PER_SQFT[business_segment]
    kwh_per_year = square_footage * intensity_kwh
    return round(kwh_per_year / 1000, 2)