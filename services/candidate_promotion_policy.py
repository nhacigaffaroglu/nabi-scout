"""Deterministic YENI candidate promotion policy.

Bridges Participation-approved US equities that already have official
universe-expansion discovery evidence into investment_candidates as YENI.

Does not assess Participation, score securities, or start active research.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from config.universe_expansion_sources import UNIVERSE_EXPANSION_SOURCES
from services.bist_symbol_mapping import US_MARKETS
from services.participation_authority import (
    AUTHORITY_SOURCE_SNAPSHOT,
    resolve_authoritative_participation,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.research_workflow_service import DEFAULT_RESEARCH_STATUS
from services.security_master_contract import (
    INSTRUMENT_EQUITY,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
)
from services.universe_expansion_contract import EXPANSION_STATUS_COMPLETED
from services.wealth_contract import normalize_symbol


REASON_PARTICIPATION_NOT_UYGUN = "PARTICIPATION_NOT_UYGUN"
REASON_IDENTITY_MISSING = "IDENTITY_MISSING"
REASON_IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
REASON_UNSUPPORTED_INSTRUMENT = "UNSUPPORTED_INSTRUMENT"
REASON_CANDIDATE_ALREADY_EXISTS = "CANDIDATE_ALREADY_EXISTS"
REASON_NO_RESEARCH_EVIDENCE = "NO_RESEARCH_EVIDENCE"
REASON_PROMOTION_ELIGIBLE = "PROMOTION_ELIGIBLE"

EVIDENCE_UNIVERSE_EXPANSION_COMPLETED = "universe_expansion_completed"
PROMOTION_DATA_SOURCE = "universe_expansion"

OFFICIAL_DISCOVERY_UNIVERSES = frozenset(
    str(source["key"]) for source in UNIVERSE_EXPANSION_SOURCES
)
US_LISTING_EXCHANGES = frozenset(
    {"NYSE", "NASDAQ", "AMEX", "NYSEARCA", "NYSEAMERICAN", "NASDAQCM", "NASDAQGM", "BATS", "ARCA"}
)


@dataclass(frozen=True)
class CandidatePromotionEvidence:
    source: str
    source_universe: Optional[str] = None
    queue_status: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_universe": self.source_universe,
            "queue_status": self.queue_status,
        }


@dataclass(frozen=True)
class CandidatePromotionDecision:
    symbol: str
    eligible: bool
    reason_codes: tuple[str, ...]
    evidence: tuple[CandidatePromotionEvidence, ...] = field(default_factory=tuple)
    participation_status: Optional[str] = None
    identity_status: Optional[str] = None
    instrument_type: Optional[str] = None
    candidate_exists: bool = False
    research_status_if_promoted: str = DEFAULT_RESEARCH_STATUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "eligible": self.eligible,
            "reason_codes": list(self.reason_codes),
            "evidence": [item.to_dict() for item in self.evidence],
            "participation_status": self.participation_status,
            "identity_status": self.identity_status,
            "instrument_type": self.instrument_type,
            "candidate_exists": self.candidate_exists,
            "research_status_if_promoted": self.research_status_if_promoted,
        }


def official_discovery_evidence(
    queue_row: Optional[Mapping[str, Any]],
) -> Optional[CandidatePromotionEvidence]:
    """Persisted official expansion completion — not Participation itself."""
    if not queue_row:
        return None
    status = str(queue_row.get("status") or "").strip()
    source_universe = str(queue_row.get("source_universe") or "").strip()
    if status != EXPANSION_STATUS_COMPLETED:
        return None
    if source_universe not in OFFICIAL_DISCOVERY_UNIVERSES:
        return None
    return CandidatePromotionEvidence(
        source=EVIDENCE_UNIVERSE_EXPANSION_COMPLETED,
        source_universe=source_universe,
        queue_status=status,
    )


def _is_us_equity_resolution(resolution: Any) -> bool:
    if resolution is None:
        return False
    if getattr(resolution, "status", None) != RESOLUTION_RESOLVED:
        return False
    if str(getattr(resolution, "instrument_type", "") or "").strip().upper() != INSTRUMENT_EQUITY:
        return False
    exchange = ""
    facts = getattr(resolution, "facts", ()) or ()
    if facts:
        exchange = str(getattr(facts[0], "exchange", None) or "").strip().upper()
    if exchange in US_LISTING_EXCHANGES or exchange in US_MARKETS:
        return True
    return False


def evaluate_candidate_promotion(
    symbol: str,
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    resolution: Any = None,
    queue_row: Optional[Mapping[str, Any]] = None,
    existing_candidates: Sequence[Mapping[str, Any]] = (),
) -> CandidatePromotionDecision:
    normalized = normalize_symbol(symbol)
    reasons: list[str] = []
    authority = resolve_authoritative_participation(normalized, snapshot=snapshot)
    participation_status = authority.status or None
    identity_status = getattr(resolution, "status", None) if resolution is not None else None
    instrument_type = getattr(resolution, "instrument_type", None) if resolution is not None else None
    existing = [row for row in existing_candidates if normalize_symbol(row.get("symbol")) == normalized]
    candidate_exists = bool(existing)
    evidence_item = official_discovery_evidence(queue_row)
    evidence = (evidence_item,) if evidence_item else ()

    if (
        not snapshot
        or authority.source != AUTHORITY_SOURCE_SNAPSHOT
        or authority.status != PARTICIPATION_STATUS_UYGUN
    ):
        reasons.append(REASON_PARTICIPATION_NOT_UYGUN)
    if resolution is None or identity_status in {None, RESOLUTION_UNKNOWN}:
        reasons.append(REASON_IDENTITY_MISSING)
    elif identity_status == RESOLUTION_CONFLICT:
        reasons.append(REASON_IDENTITY_CONFLICT)
    elif not _is_us_equity_resolution(resolution):
        reasons.append(REASON_UNSUPPORTED_INSTRUMENT)
    if candidate_exists:
        reasons.append(REASON_CANDIDATE_ALREADY_EXISTS)
    if evidence_item is None:
        reasons.append(REASON_NO_RESEARCH_EVIDENCE)

    eligible = not reasons
    if eligible:
        reasons.append(REASON_PROMOTION_ELIGIBLE)
    return CandidatePromotionDecision(
        symbol=normalized,
        eligible=eligible,
        reason_codes=tuple(reasons),
        evidence=evidence,
        participation_status=participation_status,
        identity_status=identity_status,
        instrument_type=instrument_type,
        candidate_exists=candidate_exists,
        research_status_if_promoted=DEFAULT_RESEARCH_STATUS,
    )


def build_promotion_payload(decision: CandidatePromotionDecision) -> dict[str, Any]:
    return {
        "symbol": decision.symbol,
        "market": "US",
        "asset_type": "equity",
        "research_status": DEFAULT_RESEARCH_STATUS,
        "data_source": PROMOTION_DATA_SOURCE,
    }
