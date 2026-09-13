"""Observe parity between live SI research view and persisted 8E authority.

The persisted Security Intelligence snapshot remains the decision authority.
This module does not evaluate portfolio decisions and does not write snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from services.security_intelligence_contract import (
    SecurityIntelligenceSnapshot,
    SecurityIntelligenceView,
    persisted_snapshot_is_stale,
    snapshot_from_view,
)
from services.security_intelligence_snapshot_service import (
    summarise_security_intelligence_data_quality,
)


PERSISTED_SI_DECISION_AUTHORITY = "persisted_security_intelligence_snapshot"
LIVE_SI_ROLE = "research_view"


class SecurityIntelligenceParityStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    PERSISTED_MISSING = "PERSISTED_MISSING"


@dataclass(frozen=True)
class SecurityIntelligenceAuthorityProjection:
    overall_score: Optional[float]
    investment_state: Optional[str]
    overall_confidence: Optional[float]
    stale: bool
    data_quality: Optional[str]


@dataclass(frozen=True)
class SecurityIntelligenceAuthorityParity:
    authority: str
    live_role: str
    status: SecurityIntelligenceParityStatus
    mismatched_fields: tuple[str, ...]
    live: SecurityIntelligenceAuthorityProjection
    persisted: Optional[SecurityIntelligenceAuthorityProjection]


_AUTHORITY_FIELDS = (
    "overall_score",
    "investment_state",
    "overall_confidence",
    "stale",
    "data_quality",
)


def _text(value: object) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _number(value: object) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 6)


def _projection(
    snapshot: SecurityIntelligenceSnapshot,
) -> SecurityIntelligenceAuthorityProjection:
    return SecurityIntelligenceAuthorityProjection(
        overall_score=_number(snapshot.overall_score),
        investment_state=_text(snapshot.investment_state),
        overall_confidence=_number(snapshot.overall_confidence),
        stale=persisted_snapshot_is_stale(snapshot),
        data_quality=summarise_security_intelligence_data_quality(
            snapshot.data_quality
        ),
    )


def compare_security_intelligence_authority(
    live_view: SecurityIntelligenceView,
    persisted_snapshot: Optional[SecurityIntelligenceSnapshot],
) -> SecurityIntelligenceAuthorityParity:
    """Compare only SI fields that carry 8E decision meaning.

    Timestamps, reason-code detail, dimensions, facts/engine versions, and risk
    flags are not compared directly. They matter only when an existing stale
    marker changes the canonical ``stale`` projection.
    """
    live = _projection(snapshot_from_view(live_view))
    if persisted_snapshot is None:
        return SecurityIntelligenceAuthorityParity(
            authority=PERSISTED_SI_DECISION_AUTHORITY,
            live_role=LIVE_SI_ROLE,
            status=SecurityIntelligenceParityStatus.PERSISTED_MISSING,
            mismatched_fields=(),
            live=live,
            persisted=None,
        )

    persisted = _projection(persisted_snapshot)
    mismatched = tuple(
        field
        for field in _AUTHORITY_FIELDS
        if getattr(live, field) != getattr(persisted, field)
    )
    return SecurityIntelligenceAuthorityParity(
        authority=PERSISTED_SI_DECISION_AUTHORITY,
        live_role=LIVE_SI_ROLE,
        status=(
            SecurityIntelligenceParityStatus.MISMATCH
            if mismatched
            else SecurityIntelligenceParityStatus.MATCH
        ),
        mismatched_fields=mismatched,
        live=live,
        persisted=persisted,
    )
