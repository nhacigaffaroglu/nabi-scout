"""Canonical Fund Intelligence evaluation.

Intrinsic product assessment only. Does not size New Money or infer
Participation from ticker/name. Purification is metadata, never a score input.
"""

from __future__ import annotations

from typing import Optional

from services.fund_product_contract import (
    DIM_CONCENTRATION_EVAL,
    DIM_COST_EVAL,
    DIM_COUNTRY_CONCENTRATION,
    DIM_CREDIT_QUALITY,
    DIM_CURRENCY_EXPOSURE,
    DIM_DIVERSIFICATION_EVAL,
    DIM_DURATION,
    DIM_ISSUER_CONCENTRATION,
    DIM_LIQUIDITY_EVAL,
    DIM_MOMENTUM_EVAL,
    DIM_PARTICIPATION_MANDATE,
    DIM_PERFORMANCE_EVAL,
    DIM_PORTFOLIO_FIT_EVAL,
    DIM_REAL_ESTATE_CONCENTRATION,
    DIM_RISK_EVAL,
    DIM_STATUS_MISSING,
    DIM_STATUS_NOT_APPLICABLE,
    DIM_STATUS_READY,
    DIM_TRACKING_EVAL,
    DIM_YIELD,
    EQUITY_ETF_WEIGHTS,
    FUND_EVAL_ENGINE_VERSION,
    FUND_EVAL_FACTS_VERSION,
    FundDimensionResult,
    FundFacts,
    FundIntelligenceEvaluation,
    FundLookthroughSummary,
    FundParticipationGate,
    FundPurificationEvidence,
    FundShariaEvidence,
    OfficialFundPerformance,
    MIN_READY_SCORED_DIMENSIONS,
    MIN_READY_WEIGHT_COVERAGE,
    OfficialFundMandate,
    PROFILE_EQUITY_ETF,
    PROFILE_REIT_ETF,
    PROFILE_SUKUK_ETF,
    READINESS_READY_NOW,
    REIT_ETF_WEIGHTS,
    RETURN_RISK_FAMILY,
    SUKUK_ETF_WEIGHTS,
)
from services.nabi_score_v4 import inverse, scale
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.security_intelligence_contract import (
    STATE_ATTRACTIVE,
    STATE_AVOID,
    STATE_CAUTION,
    STATE_INSUFFICIENT_DATA,
    STATE_NEUTRAL,
    STATE_WATCH,
)


def profile_for_mandate(mandate: Optional[OfficialFundMandate]) -> str:
    layer = str(mandate.primary_layer or "").strip().lower() if mandate else ""
    if layer == "sukuk":
        return PROFILE_SUKUK_ETF
    if layer == "real_estate":
        return PROFILE_REIT_ETF
    return PROFILE_EQUITY_ETF


def weights_for_profile(profile: str, *, region: str = "") -> dict[str, float]:
    if profile == PROFILE_SUKUK_ETF:
        return dict(SUKUK_ETF_WEIGHTS)
    if profile == PROFILE_REIT_ETF:
        return dict(REIT_ETF_WEIGHTS)
    weights = dict(EQUITY_ETF_WEIGHTS)
    if str(region or "").upper() == "US":
        weights.pop(DIM_COUNTRY_CONCENTRATION, None)
        weights.pop(DIM_CURRENCY_EXPOSURE, None)
    return weights


def evaluate_fund_participation_gate(
    sharia: Optional[FundShariaEvidence],
) -> FundParticipationGate:
    if sharia is None:
        return FundParticipationGate(
            eligible=False,
            status=DIM_STATUS_MISSING,
            official_mandate_present=False,
            official_certificate_listed=False,
            limitation="OFFICIAL_SHARIA_EVIDENCE_MISSING",
        )
    adverse = any(
        token in " ".join(sharia.limitations).upper()
        for token in ("ADVERSE", "NON_COMPLIANT", "UYGUN_DEGIL")
    )
    if adverse or sharia.participation_status == "Uygun Değil":
        return FundParticipationGate(
            eligible=False,
            status="ADVERSE",
            official_mandate_present=bool(sharia.official_mandate_present),
            official_certificate_listed=bool(sharia.official_certificate_listed),
            limitation="ADVERSE_OFFICIAL_SHARIA_EVIDENCE",
        )
    ready = (
        bool(sharia.official_mandate_present)
        and bool(sharia.official_certificate_listed)
        and sharia.eligibility_ready == READINESS_READY_NOW
        and bool(sharia.methodology)
    )
    if ready:
        return FundParticipationGate(
            eligible=True,
            status=DIM_STATUS_READY,
            official_mandate_present=True,
            official_certificate_listed=True,
        )
    return FundParticipationGate(
        eligible=False,
        status=DIM_STATUS_MISSING,
        official_mandate_present=bool(sharia.official_mandate_present),
        official_certificate_listed=bool(sharia.official_certificate_listed),
        limitation="OFFICIAL_SHARIA_EVIDENCE_INCOMPLETE",
    )


def fund_participation_status_for_decision(gate: FundParticipationGate) -> Optional[str]:
    """8E eligibility from official fund Sharia. Does not rewrite evidence Uygun."""
    if gate.status == "ADVERSE":
        return PARTICIPATION_STATUS_UYGUN_DEGIL
    if gate.eligible:
        return PARTICIPATION_STATUS_UYGUN
    return None


def _missing(name: str, *facts: str) -> FundDimensionResult:
    return FundDimensionResult(
        name=name,
        status=DIM_STATUS_MISSING,
        missing_facts=facts,
        reason_codes=("OFFICIAL_EVIDENCE_MISSING",),
    )


def _na(name: str, note: str) -> FundDimensionResult:
    return FundDimensionResult(
        name=name,
        status=DIM_STATUS_NOT_APPLICABLE,
        reason_codes=(note,),
    )


def _ready(name: str, score: Optional[float], *facts: str) -> FundDimensionResult:
    return FundDimensionResult(
        name=name,
        status=DIM_STATUS_READY,
        score=score,
        confidence=1.0 if score is not None else 0.6,
        facts_used=facts,
    )


def _cost_score(expense_ratio: Optional[float]) -> Optional[float]:
    if expense_ratio is None:
        return None
    return inverse(expense_ratio, 0.15, 0.80)


def _concentration_score(top_weight: Optional[float], top10: Optional[float]) -> Optional[float]:
    if top_weight is None:
        return None
    single = inverse(top_weight, 5.0, 40.0)
    if top10 is None:
        return single
    return (single + inverse(top10, 25.0, 90.0)) / 2.0


def _diversification_score(count: Optional[int], unknown_pct: Optional[float]) -> Optional[float]:
    if count is None:
        return None
    base = scale(float(count), 15.0, 120.0)
    if unknown_pct is None:
        return base
    return max(0.0, base - min(unknown_pct, 40.0))


def _liquidity_score(net_assets: Optional[float]) -> Optional[float]:
    if net_assets is None:
        return None
    return scale(net_assets / 1_000_000.0, 50.0, 2500.0)


def _lookthrough_ready(lookthrough: Optional[FundLookthroughSummary]) -> bool:
    return lookthrough is not None and lookthrough.holdings_count > 0


def evaluate_official_fund_intelligence(
    symbol: str,
    *,
    provider: Optional[object] = None,
    lookthrough: Optional[FundLookthroughSummary] = None,
    performance: Optional[OfficialFundPerformance] = None,
    historical_performance_present: bool = False,
    official_risk_series_present: bool = False,
) -> FundIntelligenceEvaluation:
    from services.official_sp_funds_product import default_official_sp_funds_provider

    fund = str(symbol or "").strip().upper()
    resolved = provider or default_official_sp_funds_provider()
    return evaluate_fund_intelligence(
        facts=resolved.facts(fund),
        mandate=resolved.mandate(fund),
        sharia=resolved.sharia_evidence(fund),
        purification=resolved.purification_evidence(fund),
        lookthrough=lookthrough,
        performance=performance,
        historical_performance_present=historical_performance_present,
        official_risk_series_present=official_risk_series_present,
    )


def evaluate_fund_intelligence(
    *,
    facts: FundFacts,
    mandate: Optional[OfficialFundMandate] = None,
    sharia: Optional[FundShariaEvidence] = None,
    purification: Optional[FundPurificationEvidence] = None,
    lookthrough: Optional[FundLookthroughSummary] = None,
    historical_performance_present: bool = False,
    official_risk_series_present: bool = False,
    official_duration_present: bool = False,
    official_yield_present: bool = False,
    official_credit_present: bool = False,
    official_country_weights: bool = False,
    official_currency_weights: bool = False,
    official_real_estate_weights: bool = False,
    performance: Optional[OfficialFundPerformance] = None,
) -> FundIntelligenceEvaluation:
    if performance is not None:
        historical_performance_present = historical_performance_present or performance.has_return_history()
        official_risk_series_present = official_risk_series_present or performance.has_risk_history()
    profile = profile_for_mandate(mandate)
    region = mandate.region if mandate else ""
    scored_weights = weights_for_profile(profile, region=region)
    participation = evaluate_fund_participation_gate(sharia)
    dimensions: list[FundDimensionResult] = [
        _ready(DIM_PARTICIPATION_MANDATE, None, "official_sharia")
        if participation.eligible
        else FundDimensionResult(
            name=DIM_PARTICIPATION_MANDATE,
            status=DIM_STATUS_MISSING if participation.status != "ADVERSE" else DIM_STATUS_READY,
            missing_facts=() if participation.eligible else ("official_sharia",),
            reason_codes=(participation.limitation,) if participation.limitation else (),
        )
    ]
    if historical_performance_present:
        perf_score = None
        if performance is not None and performance.return_1y is not None:
            perf_score = scale(performance.return_1y, -15.0, 20.0)
        elif performance is not None and performance.return_3m is not None:
            perf_score = scale(performance.return_3m, -10.0, 10.0)
        dimensions.append(_ready(DIM_PERFORMANCE_EVAL, perf_score, "official_history"))
    else:
        dimensions.append(_missing(DIM_PERFORMANCE_EVAL, "official_return_history"))
    if profile != PROFILE_SUKUK_ETF:
        if performance is not None and (performance.return_1m is not None or performance.return_3m is not None):
            lead = performance.return_3m if performance.return_3m is not None else performance.return_1m
            dimensions.append(_ready(DIM_MOMENTUM_EVAL, scale(lead, -8.0, 8.0), "official_short_horizon"))
        else:
            dimensions.append(_missing(DIM_MOMENTUM_EVAL, "official_price_history"))
    if official_risk_series_present:
        risk_score = None
        if performance is not None:
            metric = performance.drawdown if performance.drawdown is not None else performance.volatility
            if metric is not None:
                risk_score = inverse(abs(metric), 8.0, 40.0)
        dimensions.append(_ready(DIM_RISK_EVAL, risk_score, "official_drawdown"))
    else:
        dimensions.append(_missing(DIM_RISK_EVAL, "official_drawdown_series"))
    if facts.expense_ratio is not None:
        dimensions.append(_ready(DIM_COST_EVAL, _cost_score(facts.expense_ratio), "expense_ratio"))
    else:
        dimensions.append(_missing(DIM_COST_EVAL, "expense_ratio"))
    if _lookthrough_ready(lookthrough):
        dimensions.append(
            _ready(
                DIM_DIVERSIFICATION_EVAL,
                _diversification_score(lookthrough.holdings_count, lookthrough.unknown_weight_pct),
                "holdings_count",
                "unknown_weight",
            )
        )
        dimensions.append(
            _ready(
                DIM_CONCENTRATION_EVAL,
                _concentration_score(
                    lookthrough.single_name_concentration_pct,
                    lookthrough.top10_weight_pct,
                ),
                "top_holding",
                "top10",
            )
        )
    else:
        dimensions.append(_missing(DIM_DIVERSIFICATION_EVAL, "official_holdings"))
        dimensions.append(_missing(DIM_CONCENTRATION_EVAL, "official_holdings"))
    if facts.net_assets is not None and facts.market_price is not None:
        dimensions.append(_ready(DIM_LIQUIDITY_EVAL, _liquidity_score(facts.net_assets), "net_assets", "market_price"))
    else:
        dimensions.append(_missing(DIM_LIQUIDITY_EVAL, "net_assets", "market_price"))
    if profile == PROFILE_EQUITY_ETF:
        dimensions.append(_missing(DIM_TRACKING_EVAL, "official_tracking_error"))
        if region == "US":
            dimensions.append(_na(DIM_COUNTRY_CONCENTRATION, "US_EQUITY_PROFILE"))
            dimensions.append(_na(DIM_CURRENCY_EXPOSURE, "US_EQUITY_PROFILE"))
        elif official_country_weights:
            dimensions.append(_ready(DIM_COUNTRY_CONCENTRATION, None, "official_country"))
        else:
            dimensions.append(_missing(DIM_COUNTRY_CONCENTRATION, "official_country_weights"))
        if region != "US":
            if official_currency_weights:
                dimensions.append(_ready(DIM_CURRENCY_EXPOSURE, None, "official_currency"))
            else:
                dimensions.append(_missing(DIM_CURRENCY_EXPOSURE, "official_currency_weights"))
        dimensions.append(_na(DIM_DURATION, "NOT_SUKUK"))
        dimensions.append(_na(DIM_YIELD, "NOT_SUKUK"))
        dimensions.append(_na(DIM_CREDIT_QUALITY, "NOT_SUKUK"))
        dimensions.append(_na(DIM_ISSUER_CONCENTRATION, "NOT_SUKUK"))
        dimensions.append(_na(DIM_REAL_ESTATE_CONCENTRATION, "NOT_REIT"))
    elif profile == PROFILE_SUKUK_ETF:
        dimensions.append(_na(DIM_TRACKING_EVAL, "SUKUK_PROFILE"))
        dimensions.append(_na(DIM_COUNTRY_CONCENTRATION, "SUKUK_PROFILE"))
        dimensions.append(_na(DIM_CURRENCY_EXPOSURE, "SUKUK_PROFILE"))
        dimensions.append(_na(DIM_REAL_ESTATE_CONCENTRATION, "NOT_REIT"))
        dimensions.append(
            _ready(DIM_DURATION, None, "official_duration")
            if official_duration_present
            else _missing(DIM_DURATION, "official_duration")
        )
        dimensions.append(
            _ready(DIM_YIELD, None, "official_yield")
            if official_yield_present
            else _missing(DIM_YIELD, "official_yield")
        )
        dimensions.append(
            _ready(DIM_CREDIT_QUALITY, None, "official_credit")
            if official_credit_present
            else _missing(DIM_CREDIT_QUALITY, "official_credit")
        )
        if _lookthrough_ready(lookthrough):
            dimensions.append(
                _ready(
                    DIM_ISSUER_CONCENTRATION,
                    _concentration_score(lookthrough.single_name_concentration_pct, None),
                    "top_holding",
                )
            )
        else:
            dimensions.append(_missing(DIM_ISSUER_CONCENTRATION, "official_holdings"))
    else:
        dimensions.append(_na(DIM_TRACKING_EVAL, "REIT_PROFILE"))
        dimensions.append(_na(DIM_DURATION, "NOT_SUKUK"))
        dimensions.append(_na(DIM_YIELD, "NOT_SUKUK"))
        dimensions.append(_na(DIM_CREDIT_QUALITY, "NOT_SUKUK"))
        dimensions.append(_na(DIM_ISSUER_CONCENTRATION, "NOT_SUKUK"))
        if official_real_estate_weights:
            dimensions.append(_ready(DIM_REAL_ESTATE_CONCENTRATION, None, "official_re_weights"))
        else:
            dimensions.append(_missing(DIM_REAL_ESTATE_CONCENTRATION, "official_re_classification"))
        if official_country_weights:
            dimensions.append(_ready(DIM_COUNTRY_CONCENTRATION, None, "official_country"))
        else:
            dimensions.append(_missing(DIM_COUNTRY_CONCENTRATION, "official_country_weights"))
        dimensions.append(_na(DIM_CURRENCY_EXPOSURE, "OPTIONAL_REIT"))
    dimensions.append(_na(DIM_PORTFOLIO_FIT_EVAL, "OWNED_BY_8E"))

    by_name = {row.name: row for row in dimensions}
    applicable_weights = {
        name: weight
        for name, weight in scored_weights.items()
        if by_name.get(name) is None or by_name[name].status != DIM_STATUS_NOT_APPLICABLE
    }
    ready_scored = [
        (by_name[name], weight)
        for name, weight in applicable_weights.items()
        if by_name.get(name) is not None
        and by_name[name].status == DIM_STATUS_READY
        and by_name[name].score is not None
    ]
    ready_weight = sum(
        weight
        for name, weight in applicable_weights.items()
        if by_name.get(name) is not None and by_name[name].status == DIM_STATUS_READY
    )
    numeric_weight = sum(weight for _, weight in ready_scored)
    applicable_weight = sum(applicable_weights.values()) or 1.0
    coverage = ready_weight / applicable_weight
    missing_evidence = tuple(
        row.name for row in dimensions if row.status == DIM_STATUS_MISSING
    )
    return_risk_ready = any(
        by_name.get(name) is not None and by_name[name].status == DIM_STATUS_READY
        for name in RETURN_RISK_FAMILY
        if name in applicable_weights
    )
    threshold_met = (
        participation.eligible
        and len(ready_scored) >= MIN_READY_SCORED_DIMENSIONS
        and coverage >= MIN_READY_WEIGHT_COVERAGE
        and return_risk_ready
    )
    score = None
    state = STATE_INSUFFICIENT_DATA
    if participation.status == "ADVERSE":
        state = STATE_AVOID
    elif threshold_met:
        score = sum((row.score or 0.0) * weight for row, weight in ready_scored) / (
            numeric_weight or 1.0
        )
        if score >= 80:
            state = STATE_ATTRACTIVE
        elif score >= 65:
            state = STATE_WATCH
        elif score >= 45:
            state = STATE_NEUTRAL
        elif score >= 30:
            state = STATE_CAUTION
        else:
            state = STATE_AVOID
    confidence = 0.0
    if participation.eligible:
        confidence = min(1.0, coverage)
    if not threshold_met:
        confidence = min(confidence, 0.45)
    provenance = (
        "official_sp_funds_product",
        "official_fund_holdings" if lookthrough is not None else "product_facts_only",
        "purification_metadata_only",
    )
    return FundIntelligenceEvaluation(
        symbol=facts.symbol,
        fund_type_profile=profile,
        state=state,
        score=None if not threshold_met else (None if score is None else round(score, 2)),
        confidence=round(confidence, 4),
        as_of=facts.as_of or facts.holdings_as_of,
        facts_version=FUND_EVAL_FACTS_VERSION,
        engine_version=FUND_EVAL_ENGINE_VERSION,
        provenance=provenance,
        dimensions=tuple(dimensions),
        participation=participation,
        missing_evidence=missing_evidence,
        publishable=participation.eligible and state != STATE_INSUFFICIENT_DATA,
        purification_factor_pct=None if purification is None else purification.latest_factor_pct,
        purification_required=None if purification is None else purification.purification_required,
    )
