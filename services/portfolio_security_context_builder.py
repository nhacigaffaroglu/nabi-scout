"""Read-only assembler for PortfolioSecurityContext (8E.2).

Feeds the 8E.1 engine from existing persisted owners. Does not live-evaluate
SI, call the facade, infer research_allowed from Uygun, or write anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from services.hybrid_exposure_allocation_policy import (
    resolve_hybrid_allocation_policy,
    resolve_hybrid_portfolio_mode,
)
from services.participation_authority import snapshot_participation_status
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_security_decision_contract import PortfolioSecurityContext
from services.research_workflow_service import normalize_research_status
from services.security_intelligence_contract import (
    SecurityIntelligenceSnapshot,
    persisted_snapshot_is_stale,
)
from services.security_intelligence_snapshot_service import latest_snapshot
from services.security_master_contract import INSTRUMENT_UNKNOWN
from services.signal_intelligence_contract import (
    CONFLICTING,
    DIRECTION_NEGATIVE,
    DIRECTION_POSITIVE,
    EVENT_SOCIAL_SIGNAL,
    MATERIAL_LEVELS,
    SignalIntelligenceContext,
    VERIFIED,
    empty_signal_context,
)
from services.wealth_contract import normalize_symbol


def _text(value: Any) -> str:
    return str(value or "").strip()


def _explicit_bool(row: Optional[Mapping[str, Any]], key: str) -> Optional[bool]:
    if not row or key not in row or row.get(key) is None:
        return None
    return bool(row.get(key))


def explicit_research_allowed(
    *,
    queue_row: Optional[Mapping[str, Any]] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
) -> Optional[bool]:
    """Persisted boolean only. Never inferred from Participation status or SI state."""
    for row in (queue_row, snapshot):
        allowed = _explicit_bool(row, "research_allowed")
        if allowed is not None:
            return allowed
    return None


def _si_state(snap: Optional[SecurityIntelligenceSnapshot]) -> Optional[str]:
    if snap is None:
        return None
    state = _text(snap.investment_state)
    return state or None


def _si_data_quality(snap: Optional[SecurityIntelligenceSnapshot]) -> Optional[str]:
    if snap is None:
        return None
    quality = snap.data_quality or {}
    for key in ("status", "freshness_status", "overall"):
        value = _text(quality.get(key))
        if value:
            return value
    return None


def _signal_flags(context: Optional[SignalIntelligenceContext]) -> tuple[bool, bool, bool, Optional[str], Optional[str]]:
    if context is None:
        return False, False, False, None, None
    conflict = "SIGNAL_CONFLICT" in context.signal_risk_flags or any(
        item.verification_status == CONFLICTING for item in context.recent_signals
    )
    material = [
        item
        for item in context.material_signals
        if item.verification_status == VERIFIED
        and item.event_type != EVENT_SOCIAL_SIGNAL
        and item.materiality in MATERIAL_LEVELS
    ]
    negative = any(item.direction == DIRECTION_NEGATIVE for item in material)
    positive = any(item.direction == DIRECTION_POSITIVE for item in material)
    return (
        conflict,
        negative,
        positive,
        context.latest_material_event_id,
        context.latest_material_event_at,
    )


def _sum_optional(values: Sequence[Optional[float]]) -> Optional[float]:
    present = [float(item) for item in values if item is not None]
    if not present:
        return None
    return sum(present)


@dataclass(frozen=True)
class PortfolioSecuritySourceBundle:
    """Already-loaded persisted facts for one symbol. Missing stays None."""

    snapshot: Optional[Mapping[str, Any]] = None
    queue_row: Optional[Mapping[str, Any]] = None
    si_snapshot: Optional[SecurityIntelligenceSnapshot] = None
    signal_context: Optional[SignalIntelligenceContext] = None
    candidate: Optional[Mapping[str, Any]] = None
    instrument_type: Optional[str] = None
    market: Optional[str] = None
    quantity: Optional[float] = None
    market_value: Optional[float] = None
    portfolio_weight: Optional[float] = None
    economic_exposure_status: Optional[str] = None
    lookthrough_only: bool = False
    target_layer: Optional[str] = None
    layer_current_weight: Optional[float] = None
    layer_target_weight: Optional[float] = None
    as_of: Optional[str] = None


def build_portfolio_security_context(
    symbol: str,
    bundle: PortfolioSecuritySourceBundle,
) -> PortfolioSecurityContext:
    normalized = normalize_symbol(symbol)
    participation = snapshot_participation_status(bundle.snapshot) or None
    research_allowed = explicit_research_allowed(
        queue_row=bundle.queue_row,
        snapshot=bundle.snapshot,
    )
    si = bundle.si_snapshot
    conflict, negative, positive, latest_signal, signal_as_of = _signal_flags(
        bundle.signal_context
    )
    candidate = bundle.candidate
    candidate_exists = candidate is not None
    research_status = (
        normalize_research_status(candidate.get("research_status")) if candidate_exists else None
    )
    qty = bundle.quantity
    is_holding = qty is not None and float(qty) > 0
    missing: list[str] = []
    if participation is None:
        missing.append("participation_status")
    if research_allowed is None:
        missing.append("research_allowed")
    if _si_state(si) is None:
        missing.append("si_state")
    if is_holding and bundle.portfolio_weight is None:
        missing.append("portfolio_weight")
    stale = ("si",) if persisted_snapshot_is_stale(si) else ()

    return PortfolioSecurityContext(
        symbol=normalized,
        participation_status=participation or None,
        research_allowed=research_allowed,
        si_state=_si_state(si),
        si_score=None if si is None else si.overall_score,
        si_confidence=None if si is None else si.overall_confidence,
        si_data_quality=_si_data_quality(si),
        si_as_of=None if si is None else si.as_of,
        verified_material_negative=negative,
        verified_material_positive=positive,
        signal_conflict=conflict,
        latest_material_signal=latest_signal,
        signal_as_of=signal_as_of,
        is_holding=is_holding,
        quantity=qty,
        market_value=bundle.market_value,
        portfolio_weight=bundle.portfolio_weight,
        concentration_ceiling=CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
        target_layer=bundle.target_layer,
        layer_current_weight=bundle.layer_current_weight,
        layer_target_weight=bundle.layer_target_weight,
        economic_exposure_status=bundle.economic_exposure_status,
        candidate_exists=candidate_exists,
        research_status=research_status,
        instrument_type=_text(bundle.instrument_type) or None,
        market=_text(bundle.market) or None,
        lookthrough_only=bool(bundle.lookthrough_only),
        missing_inputs=tuple(dict.fromkeys(missing)),
        stale_inputs=stale,
        as_of=bundle.as_of or (None if si is None else si.as_of) or signal_as_of,
    )


def identity_from_security_master(resolution: Any) -> tuple[Optional[str], Optional[str]]:
    """Copy Security Master instrument/exchange. Do not invent US EQUITY."""
    if resolution is None:
        return None, None
    instrument = _text(getattr(resolution, "instrument_type", None)) or None
    if instrument == INSTRUMENT_UNKNOWN:
        instrument = INSTRUMENT_UNKNOWN
    market = None
    for fact in getattr(resolution, "facts", ()) or ():
        market = _text(getattr(fact, "exchange", None)) or None
        if market:
            break
    return instrument, market


def load_persisted_si_snapshot(repo, symbol: str) -> Optional[SecurityIntelligenceSnapshot]:
    return latest_snapshot(repo, symbol)


def load_signal_context(service, symbol: str) -> SignalIntelligenceContext:
    if service is None:
        return empty_signal_context(symbol)
    return service.context_for(symbol)


def resolve_economic_exposure_status() -> str:
    """Existing hybrid-mode resolver. Hybrid OFF → STRICT."""
    policy = resolve_hybrid_allocation_policy()
    return resolve_hybrid_portfolio_mode(policy=policy, determinacy=None).value


def aggregate_holding(
    rows: Sequence[Any],
    symbol: str,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[str]]:
    wanted = normalize_symbol(symbol)
    matched = []
    for row in rows:
        if isinstance(row, Mapping):
            raw_symbol = row.get("symbol")
        else:
            raw_symbol = getattr(row, "symbol", None)
        if normalize_symbol(raw_symbol) == wanted:
            matched.append(row)
    if not matched:
        return None, None, None, None
    quantities = []
    values = []
    weights = []
    market = None
    for row in matched:
        if isinstance(row, Mapping):
            quantities.append(row.get("quantity"))
            values.append(row.get("market_value"))
            weights.append(row.get("weight_pct") or row.get("portfolio_weight"))
            market = market or row.get("market")
        else:
            quantities.append(getattr(row, "quantity", None))
            values.append(getattr(row, "market_value", None))
            weights.append(getattr(row, "weight_pct", None))
            market = market or getattr(row, "market", None)
    qty = _sum_optional(quantities)
    return qty, _sum_optional(values), _sum_optional(weights), _text(market) or None
