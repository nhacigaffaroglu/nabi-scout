"""Portfolio-aware Security Decision contract (8E.1).

8E answers: what should NABI consider doing with this security in THIS portfolio?

It does not assemble SecurityFacts, score Security Intelligence, ingest signals,
assess Participation, size New Money, or explain via Adviser.

Canonical SI input is an explicit persisted-snapshot representation plus an
independent research_allowed boolean. Facade live SI is not a legal 8E input.
CRM SI fact-path parity remains an 8E.4 integration blocker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

ENGINE_VERSION = "portfolio_security_decision_8e.1"

# 8E.0 approved vocabulary. No BUY / SELL / ADD.
DECISION_CONSIDER_NEW_POSITION = "CONSIDER_NEW_POSITION"
DECISION_CONSIDER_TOP_UP = "CONSIDER_TOP_UP"
DECISION_HOLD = "HOLD"
DECISION_WATCH = "WATCH"
DECISION_REVIEW = "REVIEW"
DECISION_REDUCE = "REDUCE"
DECISION_AVOID = "AVOID"
DECISION_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

PORTFOLIO_SECURITY_DECISIONS = (
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_WATCH,
    DECISION_REVIEW,
    DECISION_REDUCE,
    DECISION_AVOID,
    DECISION_INSUFFICIENT_DATA,
)

INCREASE_DECISIONS = frozenset(
    {DECISION_CONSIDER_NEW_POSITION, DECISION_CONSIDER_TOP_UP}
)

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

REASON_PARTICIPATION_NOT_UYGUN = "PARTICIPATION_NOT_UYGUN"
REASON_PARTICIPATION_MISSING = "PARTICIPATION_MISSING"
REASON_RESEARCH_NOT_ALLOWED = "RESEARCH_NOT_ALLOWED"
REASON_SI_INSUFFICIENT = "SI_INSUFFICIENT"
REASON_SI_MISSING = "SI_MISSING"
REASON_SI_STALE = "SI_STALE"
REASON_SI_AVOID = "SI_AVOID"
REASON_SI_CAUTION = "SI_CAUTION"
REASON_SI_WATCH = "SI_WATCH"
REASON_SI_NOT_ATTRACTIVE = "SI_NOT_ATTRACTIVE"
REASON_SIGNAL_CONFLICT = "SIGNAL_CONFLICT"
REASON_MATERIAL_NEGATIVE_SIGNAL = "MATERIAL_NEGATIVE_SIGNAL"
REASON_POSITIVE_SIGNAL_NOT_AUTHORITY = "POSITIVE_SIGNAL_NOT_AUTHORITY"
REASON_CONCENTRATION_LIMIT = "CONCENTRATION_LIMIT"
REASON_ECONOMIC_EXPOSURE_UNSAFE = "ECONOMIC_EXPOSURE_UNSAFE"
REASON_ECONOMIC_EXPOSURE_UNAVAILABLE = "ECONOMIC_EXPOSURE_UNAVAILABLE"
REASON_PORTFOLIO_CONTEXT_MISSING = "PORTFOLIO_CONTEXT_MISSING"
REASON_UNSUPPORTED_INSTRUMENT = "UNSUPPORTED_INSTRUMENT"
REASON_LOOKTHROUGH_NOT_IN_SCOPE = "LOOKTHROUGH_NOT_IN_SCOPE"
REASON_YENI_NOT_ACTIVE_RESEARCH = "YENI_NOT_ACTIVE_RESEARCH"
REASON_RESEARCH_TERMINAL = "RESEARCH_TERMINAL"
REASON_LAYER_UNDERWEIGHT_NOT_AUTHORITY = "LAYER_UNDERWEIGHT_NOT_AUTHORITY"
REASON_ELIGIBLE_TO_INCREASE = "ELIGIBLE_TO_INCREASE"
REASON_HOLDING_CONTEXT = "HOLDING_CONTEXT"
REASON_FACADE_SI_NOT_CANONICAL = "FACADE_SI_NOT_CANONICAL"


@dataclass(frozen=True)
class PortfolioSecurityContext:
    """Deterministic 8E inputs. Absent fields stay None; nothing is invented."""

    symbol: str
    participation_status: Optional[str] = None
    research_allowed: Optional[bool] = None
    si_state: Optional[str] = None
    si_score: Optional[float] = None
    si_confidence: Optional[float] = None
    si_data_quality: Optional[str] = None
    si_as_of: Optional[str] = None
    verified_material_negative: bool = False
    verified_material_positive: bool = False
    signal_conflict: bool = False
    latest_material_signal: Optional[str] = None
    signal_as_of: Optional[str] = None
    is_holding: bool = False
    quantity: Optional[float] = None
    market_value: Optional[float] = None
    portfolio_weight: Optional[float] = None
    concentration_ceiling: Optional[float] = None
    target_layer: Optional[str] = None
    layer_current_weight: Optional[float] = None
    layer_target_weight: Optional[float] = None
    economic_exposure_status: Optional[str] = None
    candidate_exists: bool = False
    research_status: Optional[str] = None
    instrument_type: Optional[str] = None
    market: Optional[str] = None
    lookthrough_only: bool = False
    missing_inputs: tuple[str, ...] = ()
    stale_inputs: tuple[str, ...] = ()
    as_of: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "participation_status": self.participation_status,
            "research_allowed": self.research_allowed,
            "si_state": self.si_state,
            "si_score": self.si_score,
            "si_confidence": self.si_confidence,
            "si_data_quality": self.si_data_quality,
            "si_as_of": self.si_as_of,
            "verified_material_negative": self.verified_material_negative,
            "verified_material_positive": self.verified_material_positive,
            "signal_conflict": self.signal_conflict,
            "latest_material_signal": self.latest_material_signal,
            "signal_as_of": self.signal_as_of,
            "is_holding": self.is_holding,
            "quantity": self.quantity,
            "market_value": self.market_value,
            "portfolio_weight": self.portfolio_weight,
            "concentration_ceiling": self.concentration_ceiling,
            "target_layer": self.target_layer,
            "layer_current_weight": self.layer_current_weight,
            "layer_target_weight": self.layer_target_weight,
            "economic_exposure_status": self.economic_exposure_status,
            "candidate_exists": self.candidate_exists,
            "research_status": self.research_status,
            "instrument_type": self.instrument_type,
            "market": self.market,
            "lookthrough_only": self.lookthrough_only,
            "missing_inputs": list(self.missing_inputs),
            "stale_inputs": list(self.stale_inputs),
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class PortfolioSecurityDecision:
    symbol: str
    decision: str
    confidence: str
    exposure_increase_allowed: bool
    participation_status: Optional[str]
    research_allowed: Optional[bool]
    security_intelligence_state: Optional[str]
    security_intelligence_score: Optional[float] = None
    security_intelligence_confidence: Optional[float] = None
    security_intelligence_data_quality: Optional[str] = None
    security_intelligence_as_of: Optional[str] = None
    primary_reasons: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    as_of: Optional[str] = None
    engine_version: str = ENGINE_VERSION
    research_status: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "decision": self.decision,
            "confidence": self.confidence,
            "exposure_increase_allowed": self.exposure_increase_allowed,
            "participation_status": self.participation_status,
            "research_allowed": self.research_allowed,
            "security_intelligence_state": self.security_intelligence_state,
            "security_intelligence_score": self.security_intelligence_score,
            "security_intelligence_confidence": self.security_intelligence_confidence,
            "security_intelligence_data_quality": self.security_intelligence_data_quality,
            "security_intelligence_as_of": self.security_intelligence_as_of,
            "primary_reasons": list(self.primary_reasons),
            "blocking_reasons": list(self.blocking_reasons),
            "risk_flags": list(self.risk_flags),
            "reason_codes": list(self.reason_codes),
            "as_of": self.as_of,
            "engine_version": self.engine_version,
            "research_status": self.research_status,
        }
