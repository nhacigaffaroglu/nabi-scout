"""Deterministic Portfolio-aware Security Decision engine (8E.1).

Consumes an explicit persisted-SI representation and an independent
research_allowed flag. Does not call the facade, recompute SI, assess
Participation, size New Money, or mutate candidate lifecycle.
"""

from __future__ import annotations

from typing import Optional

from services.bist_symbol_mapping import BIST_EXCHANGES, US_MARKETS
from services.hybrid_exposure_allocation_policy import HybridPortfolioMode
from services.nabi_decision_contract import (
    ACTION_CONSIDER_NEW_POSITION,
    ACTION_CONSIDER_TOP_UP,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_security_decision_contract import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DECISION_AVOID,
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REDUCE,
    DECISION_REVIEW,
    DECISION_WATCH,
    ENGINE_VERSION,
    INCREASE_DECISIONS,
    PortfolioSecurityContext,
    PortfolioSecurityDecision,
    REASON_CONCENTRATION_LIMIT,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_ECONOMIC_EXPOSURE_UNSAFE,
    REASON_ELIGIBLE_TO_INCREASE,
    REASON_HOLDING_CONTEXT,
    REASON_LAYER_UNDERWEIGHT_NOT_AUTHORITY,
    REASON_LOOKTHROUGH_NOT_IN_SCOPE,
    REASON_MATERIAL_NEGATIVE_SIGNAL,
    REASON_PARTICIPATION_MISSING,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_PORTFOLIO_CONTEXT_MISSING,
    REASON_POSITIVE_SIGNAL_NOT_AUTHORITY,
    REASON_RESEARCH_NOT_ALLOWED,
    REASON_RESEARCH_TERMINAL,
    REASON_SI_AVOID,
    REASON_SI_CAUTION,
    REASON_SI_INSUFFICIENT,
    REASON_SI_MISSING,
    REASON_SI_STALE,
    REASON_SI_NOT_ATTRACTIVE,
    REASON_SI_WATCH,
    REASON_SIGNAL_CONFLICT,
    REASON_UNSUPPORTED_INSTRUMENT,
    REASON_YENI_NOT_ACTIVE_RESEARCH,
)
from services.research_workflow_service import DEFAULT_RESEARCH_STATUS, normalize_research_status
from services.security_intelligence_contract import (
    STATE_ATTRACTIVE,
    STATE_AVOID,
    STATE_CAUTION,
    STATE_INSUFFICIENT_DATA,
    STATE_NEUTRAL,
    STATE_WATCH,
)
from services.security_master_contract import INSTRUMENT_EQUITY, INSTRUMENT_ETF
from services.signal_ingestion_universe import ACTIVE_RESEARCH_STATUSES, TR_MARKETS
from services.wealth_asset_classification import KNOWN_ETF_SYMBOLS
from services.wealth_contract import ASSET_CLASS_ETF, ASSET_CLASS_FUND, normalize_symbol


assert DECISION_CONSIDER_NEW_POSITION == ACTION_CONSIDER_NEW_POSITION
assert DECISION_CONSIDER_TOP_UP == ACTION_CONSIDER_TOP_UP

_UNSUPPORTED_TYPES = frozenset(
    {INSTRUMENT_ETF, "FUND", ASSET_CLASS_ETF.upper(), ASSET_CLASS_FUND.upper(), "REIT"}
)


def _text(value: Optional[str]) -> str:
    return str(value or "").strip()


def _layer_underweight(ctx: PortfolioSecurityContext) -> bool:
    if ctx.layer_current_weight is None or ctx.layer_target_weight is None:
        return False
    return ctx.layer_current_weight < ctx.layer_target_weight


def _concentration_breached(ctx: PortfolioSecurityContext) -> Optional[bool]:
    if not ctx.is_holding:
        return False
    if ctx.portfolio_weight is None:
        return None
    ceiling = (
        ctx.concentration_ceiling
        if ctx.concentration_ceiling is not None
        else CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT
    )
    return ctx.portfolio_weight >= ceiling


def _is_bist_portfolio_market(market: str) -> bool:
    return bool(market) and (market in TR_MARKETS or market in BIST_EXCHANGES)


def supports_portfolio_decision(
    *,
    instrument_type: Optional[str] = None,
    market: Optional[str] = None,
    symbol: Optional[str] = None,
    lookthrough_only: bool = False,
) -> bool:
    """US EQUITY stays supported. Canonical BIST EQUITY is supported.

    No symbol allowlist. Other instruments and markets keep existing
    fail-closed UNSUPPORTED_INSTRUMENT behavior.
    """
    if lookthrough_only:
        return False
    symbol_n = normalize_symbol(symbol)
    instrument = _text(instrument_type).upper()
    market_n = _text(market).upper()
    if symbol_n in KNOWN_ETF_SYMBOLS:
        return False
    if instrument in _UNSUPPORTED_TYPES:
        return False
    if instrument and instrument != INSTRUMENT_EQUITY:
        return False
    if _is_bist_portfolio_market(market_n):
        return instrument == INSTRUMENT_EQUITY
    if market_n and market_n not in US_MARKETS:
        return False
    return True


def _scope_block(ctx: PortfolioSecurityContext) -> Optional[str]:
    if ctx.lookthrough_only:
        return REASON_LOOKTHROUGH_NOT_IN_SCOPE
    if supports_portfolio_decision(
        instrument_type=ctx.instrument_type,
        market=ctx.market,
        symbol=ctx.symbol,
        lookthrough_only=ctx.lookthrough_only,
    ):
        return None
    return REASON_UNSUPPORTED_INSTRUMENT


def _workflow(ctx: PortfolioSecurityContext) -> Optional[str]:
    if ctx.research_status is None and not ctx.candidate_exists:
        return None
    return normalize_research_status(ctx.research_status)


def _confidence(decision: str, missing: tuple[str, ...]) -> str:
    if decision == DECISION_INSUFFICIENT_DATA or missing:
        return CONFIDENCE_LOW
    if decision in INCREASE_DECISIONS:
        return CONFIDENCE_HIGH
    if decision in {DECISION_HOLD, DECISION_REDUCE} and not missing:
        return CONFIDENCE_HIGH
    return CONFIDENCE_MEDIUM


def _finish(
    ctx: PortfolioSecurityContext,
    *,
    symbol: str,
    decision: str,
    reasons: list[str],
    blocking: list[str],
    flags: list[str],
    missing: list[str],
    participation: Optional[str],
    si_state: Optional[str],
    workflow: Optional[str],
) -> PortfolioSecurityDecision:
    unique_reasons = tuple(dict.fromkeys(reasons))
    unique_blocking = tuple(dict.fromkeys(blocking))
    unique_flags = tuple(dict.fromkeys(flags))
    unique_missing = tuple(dict.fromkeys(missing))
    increase = decision in INCREASE_DECISIONS and not unique_blocking
    if not increase:
        unique_reasons = tuple(
            code for code in unique_reasons if code != REASON_ELIGIBLE_TO_INCREASE
        )
    return PortfolioSecurityDecision(
        symbol=symbol,
        decision=decision,
        confidence=_confidence(decision, unique_missing),
        exposure_increase_allowed=increase,
        participation_status=participation,
        research_allowed=ctx.research_allowed,
        security_intelligence_state=si_state,
        security_intelligence_score=ctx.si_score,
        security_intelligence_confidence=ctx.si_confidence,
        security_intelligence_data_quality=ctx.si_data_quality,
        security_intelligence_as_of=ctx.si_as_of,
        primary_reasons=(unique_reasons or unique_blocking)[:3],
        blocking_reasons=unique_blocking,
        risk_flags=unique_flags,
        reason_codes=tuple(dict.fromkeys((*unique_reasons, *unique_blocking))),
        as_of=ctx.as_of,
        engine_version=ENGINE_VERSION,
        research_status=workflow,
    )


def evaluate_portfolio_security_decision(
    context: PortfolioSecurityContext,
) -> PortfolioSecurityDecision:
    """Evaluate one explicit context. Never loads facade SI or writes."""
    symbol = normalize_symbol(context.symbol)
    participation = _text(context.participation_status) or None
    si_state = _text(context.si_state) or None
    workflow = _workflow(context)
    reasons: list[str] = []
    blocking: list[str] = []
    flags: list[str] = []
    missing = list(context.missing_inputs)

    def blocked(code: str, decision: str, extra: Optional[str] = None) -> PortfolioSecurityDecision:
        blocking.append(code)
        reasons.append(code)
        if extra:
            reasons.append(extra)
        return _finish(
            context,
            symbol=symbol,
            decision=decision,
            reasons=reasons,
            blocking=blocking,
            flags=flags,
            missing=missing,
            participation=participation,
            si_state=si_state,
            workflow=workflow,
        )

    scope = _scope_block(context)
    if scope:
        return blocked(scope, DECISION_INSUFFICIENT_DATA)

    if si_state is None:
        missing.append("si_state")
        return blocked(REASON_SI_MISSING, DECISION_INSUFFICIENT_DATA)
    if "si" in context.stale_inputs:
        return blocked(
            REASON_SI_STALE,
            DECISION_REVIEW if context.is_holding else DECISION_INSUFFICIENT_DATA,
        )
    if si_state == STATE_INSUFFICIENT_DATA:
        return blocked(REASON_SI_INSUFFICIENT, DECISION_INSUFFICIENT_DATA)
    if participation is None:
        missing.append("participation_status")
        return blocked(REASON_PARTICIPATION_MISSING, DECISION_INSUFFICIENT_DATA)

    if context.signal_conflict:
        flags.append(REASON_SIGNAL_CONFLICT)
        return blocked(REASON_SIGNAL_CONFLICT, DECISION_REVIEW)
    if context.verified_material_negative:
        flags.append(REASON_MATERIAL_NEGATIVE_SIGNAL)
        return blocked(REASON_MATERIAL_NEGATIVE_SIGNAL, DECISION_REVIEW)

    exposure = _text(context.economic_exposure_status).upper()
    allowed_exposure = {
        HybridPortfolioMode.STRICT.value,
        HybridPortfolioMode.COMPLETE.value,
        HybridPortfolioMode.BOUNDED.value,
    }
    if exposure == HybridPortfolioMode.UNSAFE.value:
        return blocked(
            REASON_ECONOMIC_EXPOSURE_UNSAFE,
            DECISION_REVIEW if context.is_holding else DECISION_INSUFFICIENT_DATA,
        )
    if not exposure or exposure == HybridPortfolioMode.UNAVAILABLE.value or exposure not in allowed_exposure:
        return blocked(
            REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
            DECISION_REVIEW if context.is_holding else DECISION_INSUFFICIENT_DATA,
        )

    concentrated = _concentration_breached(context)
    if concentrated is None:
        missing.append("portfolio_weight")
        return blocked(REASON_PORTFOLIO_CONTEXT_MISSING, DECISION_INSUFFICIENT_DATA)
    if concentrated:
        flags.append(REASON_CONCENTRATION_LIMIT)
        return blocked(
            REASON_CONCENTRATION_LIMIT,
            DECISION_REDUCE if context.is_holding else DECISION_WATCH,
        )

    if not context.is_holding and workflow == DEFAULT_RESEARCH_STATUS:
        return blocked(REASON_YENI_NOT_ACTIVE_RESEARCH, DECISION_WATCH)
    if not context.is_holding and workflow == "TAMAMLANDI":
        return blocked(REASON_RESEARCH_TERMINAL, DECISION_WATCH)

    if participation != PARTICIPATION_STATUS_UYGUN:
        if context.is_holding:
            held = (
                DECISION_REVIEW
                if participation == PARTICIPATION_STATUS_KONTROL_ET
                else DECISION_HOLD
            )
            return blocked(REASON_PARTICIPATION_NOT_UYGUN, held, REASON_HOLDING_CONTEXT)
        if participation == PARTICIPATION_STATUS_UYGUN_DEGIL:
            return blocked(REASON_PARTICIPATION_NOT_UYGUN, DECISION_AVOID)
        return blocked(REASON_PARTICIPATION_NOT_UYGUN, DECISION_REVIEW)

    if context.research_allowed is not True:
        return blocked(
            REASON_RESEARCH_NOT_ALLOWED,
            DECISION_HOLD if context.is_holding else DECISION_WATCH,
        )

    if si_state == STATE_AVOID:
        return blocked(
            REASON_SI_AVOID,
            DECISION_HOLD if context.is_holding else DECISION_AVOID,
        )
    if si_state == STATE_CAUTION:
        return blocked(
            REASON_SI_CAUTION,
            DECISION_REVIEW if context.is_holding else DECISION_WATCH,
        )
    if si_state in {STATE_WATCH, STATE_NEUTRAL}:
        if context.verified_material_positive:
            reasons.append(REASON_POSITIVE_SIGNAL_NOT_AUTHORITY)
        if _layer_underweight(context):
            reasons.append(REASON_LAYER_UNDERWEIGHT_NOT_AUTHORITY)
        return blocked(
            REASON_SI_WATCH if si_state == STATE_WATCH else REASON_SI_NOT_ATTRACTIVE,
            DECISION_WATCH,
        )
    if si_state != STATE_ATTRACTIVE:
        return blocked(REASON_SI_NOT_ATTRACTIVE, DECISION_WATCH)

    if not context.is_holding and workflow not in ACTIVE_RESEARCH_STATUSES:
        return blocked(REASON_YENI_NOT_ACTIVE_RESEARCH, DECISION_WATCH)

    if context.verified_material_positive:
        reasons.append(REASON_POSITIVE_SIGNAL_NOT_AUTHORITY)
    if _layer_underweight(context):
        reasons.append(REASON_LAYER_UNDERWEIGHT_NOT_AUTHORITY)
    reasons.append(REASON_ELIGIBLE_TO_INCREASE)
    if context.is_holding:
        reasons.append(REASON_HOLDING_CONTEXT)
    decision = (
        DECISION_CONSIDER_TOP_UP if context.is_holding else DECISION_CONSIDER_NEW_POSITION
    )
    return _finish(
        context,
        symbol=symbol,
        decision=decision,
        reasons=reasons,
        blocking=blocking,
        flags=flags,
        missing=missing,
        participation=participation,
        si_state=si_state,
        workflow=workflow,
    )
