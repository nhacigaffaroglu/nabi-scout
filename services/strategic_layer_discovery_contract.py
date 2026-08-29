"""Strategic-layer discovery records. Not classification evidence.

discovery_reason explains why a symbol was proposed (ROBUST_UW:sukuk /
ROBUST_UW:real_estate). It must never authorize economic_layer, Participation,
or New Money eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.universe_listing_identity import STRATEGIC_LAYER_DISCOVERY_SOURCE

REASON_ROBUST_UW_SUKUK = "ROBUST_UW:sukuk"
REASON_ROBUST_UW_REAL_ESTATE = "ROBUST_UW:real_estate"
DISCOVERY_REASONS = frozenset({REASON_ROBUST_UW_SUKUK, REASON_ROBUST_UW_REAL_ESTATE})

CLASSIFICATION_PASS = "PASS"
CLASSIFICATION_FAIL = "FAIL"
CLASSIFICATION_UNKNOWN = "UNKNOWN"

PARTICIPATION_NOT_RUN = "NOT_RUN"
ACTIONABILITY_PASS = "PASS"
ACTIONABILITY_FAIL = "FAIL"
ACTIONABILITY_NOT_RUN = "NOT_RUN"

SUPPORT_FULL = "FULLY_SUPPORTED"
SUPPORT_PARTIAL = "PARTIALLY_SUPPORTED"
SUPPORT_UNSUPPORTED = "UNSUPPORTED"

GATE_ELIGIBLE = "ELIGIBLE_FILLER"
GATE_BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class StrategicDiscoveryRecord:
    symbol: str
    name: str
    instrument_identity: str
    exchange: str
    country: str
    provider_identifiers: dict[str, str]
    economic_layer_candidate: str
    classification_evidence: str
    classification_status: str
    participation_status: str
    research_allowed: Optional[bool]
    actionability: str
    discovery_source: str = STRATEGIC_LAYER_DISCOVERY_SOURCE
    discovery_reason: str = ""
    provider_support: str = SUPPORT_UNSUPPORTED
    lookthrough_feasibility: str = ""
    limitation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "instrument_identity": self.instrument_identity,
            "exchange": self.exchange,
            "country": self.country,
            "provider_identifiers": dict(self.provider_identifiers or {}),
            "economic_layer_candidate": self.economic_layer_candidate,
            "classification_evidence": self.classification_evidence,
            "classification_status": self.classification_status,
            "participation_status": self.participation_status,
            "research_allowed": self.research_allowed,
            "actionability": self.actionability,
            "discovery_source": self.discovery_source,
            "discovery_reason": self.discovery_reason,
            "provider_support": self.provider_support,
            "lookthrough_feasibility": self.lookthrough_feasibility,
            "limitation": self.limitation,
        }


def three_gate_eligibility(
    *,
    classification_status: str,
    participation_status: str,
    actionability: str,
    discovery_reason: str = "",
) -> str:
    """Eligible only when all three gates pass. Reason is ignored."""
    del discovery_reason
    if str(classification_status or "").strip().upper() != CLASSIFICATION_PASS:
        return GATE_BLOCKED
    if str(participation_status or "").strip() != "Uygun":
        return GATE_BLOCKED
    if str(actionability or "").strip().upper() != ACTIONABILITY_PASS:
        return GATE_BLOCKED
    return GATE_ELIGIBLE
