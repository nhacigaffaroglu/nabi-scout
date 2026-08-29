"""Deterministic Security Master identifier matching.

Matches only when the assessed identifier type is factually compatible with
the stored fact type. Never cross-matches a SEDOL-shaped string to TICKER.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from services.security_identifier_validation import (
    IdentifierAssessment,
    assess_identifier,
)
from services.security_master_contract import (
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_ISIN,
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
    SecurityResolution,
)
from services.security_master_service import SecurityMasterService

COMPATIBLE_TYPES = {
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_ISIN,
    IDENTIFIER_TYPE_TICKER,
}


@dataclass(frozen=True)
class IdentifierMatch:
    assessment: IdentifierAssessment
    status: str
    resolution: Optional[SecurityResolution] = None
    matched_weight_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment": self.assessment.to_dict(),
            "status": self.status,
            "resolution": None if self.resolution is None else self.resolution.to_dict(),
        }


def match_identifier_to_security_master(
    raw: Any,
    *,
    security_master: SecurityMasterService,
    assessment: Optional[IdentifierAssessment] = None,
) -> IdentifierMatch:
    judged = assessment or assess_identifier(raw)
    if judged.identifier is None or judged.identifier_type not in COMPATIBLE_TYPES:
        return IdentifierMatch(assessment=judged, status="UNMATCHED")
    resolution = security_master.resolve_security(
        judged.identifier,
        identifier_type=judged.identifier_type,
    )
    if resolution.status == RESOLUTION_CONFLICT:
        return IdentifierMatch(assessment=judged, status="CONFLICT", resolution=resolution)
    if resolution.status == RESOLUTION_RESOLVED:
        return IdentifierMatch(
            assessment=judged,
            status="EXACT",
            resolution=resolution,
            matched_weight_applied=True,
        )
    return IdentifierMatch(assessment=judged, status="UNMATCHED", resolution=resolution)


def match_official_holding(
    *,
    ticker: Any,
    cusip_raw: Any,
    security_master: SecurityMasterService,
) -> tuple[IdentifierMatch, IdentifierMatch]:
    """Match each official column independently. No cross-type fallback."""
    ticker_match = match_identifier_to_security_master(ticker, security_master=security_master)
    cusip_match = match_identifier_to_security_master(cusip_raw, security_master=security_master)
    return ticker_match, cusip_match


def first_exact_match(matches: Sequence[IdentifierMatch]) -> Optional[IdentifierMatch]:
    exact = [row for row in matches if row.status == "EXACT"]
    if not exact:
        return None
    types = {
        (row.resolution.instrument_type if row.resolution else None)
        for row in exact
    }
    if len(types) > 1:
        return None
    return exact[0]
