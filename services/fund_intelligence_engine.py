"""Canonical Fund Intelligence evaluation.

Intrinsic product assessment only. Does not size New Money or infer
Participation from ticker/name. Purification is metadata, never a score input.
"""

from __future__ import annotations

from typing import Optional

from services.fund_lookthrough_summary import (
    CONCENTRATED_EFFECTIVE_N,
    DIVERSIFICATION_EFFECTIVE_N_BAD,
    DIVERSIFICATION_EFFECTIVE_N_GOOD,
    LARGE_COUNT_FOR_HHI_OVERRIDE,
    build_fund_lookthrough_summary,
    holdings_reliable,
)
from services.fund_product_contract import (
    DIM_CONCENTRATION_EVAL,
    DIM_COST_EVAL,
    DIM_COUNTRY_CONCENTRATION,
    DIM_CREDIT_QUALITY,
    DIM_CREDIT_RISK,
    DIM_CURRENCY_DENOMINATION,
    DIM_DEVELOPED_EMERGING,
    DIM_CURRENCY_EXPOSURE,
    DIM_DIVERSIFICATION_EVAL,
    DIM_DURATION,
    DIM_ISSUER_CONCENTRATION,
    DIM_LIQUIDITY_EVAL,
    DIM_MATURITY,
    DIM_MOMENTUM_EVAL,
    DIM_PARTICIPATION_MANDATE,
    DIM_PERFORMANCE_EVAL,
    DIM_PORTFOLIO_FIT_EVAL,
    DIM_RATE_RISK,
    DIM_REAL_ESTATE_CONCENTRATION,
    DIM_RISK_EVAL,
    DIM_STATUS_MISSING,
    DIM_STATUS_NOT_APPLICABLE,
    DIM_STATUS_READY,
    DIM_TRACKING_EVAL,
    DIM_YIELD,
    EQUITY_ETF_WEIGHTS,
    EQUITY_PARTICIPATION_FUND_WEIGHTS,
    FUND_EVAL_ENGINE_VERSION,
    FUND_EVAL_FACTS_VERSION,
    FundDimensionResult,
    FundFacts,
    FundExposureEvidence,
    FundFixedIncomeRiskEvidence,
    FundIntelligenceEvaluation,
    FundLookthroughSummary,
    FundParticipationGate,
    FundPurificationEvidence,
    FundShariaEvidence,
    OfficialFundPerformance,
    OfficialFundYield,
    LIQUIDITY_PARTICIPATION_FUND_WEIGHTS,
    MANAGEMENT_FEE_BAD_PCT,
    MANAGEMENT_FEE_GOOD_PCT,
    MIN_READY_SCORED_DIMENSIONS,
    MIN_READY_WEIGHT_COVERAGE,
    OfficialFundMandate,
    PRECIOUS_METALS_PARTICIPATION_FUND_WEIGHTS,
    MIXED_MULTI_ASSET_PARTICIPATION_FUND_WEIGHTS,
    PROFILE_EQUITY_ETF,
    PROFILE_EQUITY_PARTICIPATION_FUND,
    PROFILE_LIQUIDITY_PARTICIPATION_FUND,
    PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND,
    PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND,
    PROFILE_REAL_ESTATE_PARTICIPATION_FUND,
    PROFILE_REIT_ETF,
    PROFILE_SUKUK_ETF,
    PROFILE_SUKUK_PARTICIPATION_FUND,
    READINESS_READY_NOW,
    REIT_ETF_WEIGHTS,
    REAL_ESTATE_PARTICIPATION_FUND_WEIGHTS,
    RETURN_RISK_FAMILY,
    RISK_FACT_HISTORICAL_MAX_DRAWDOWN,
    RISK_FACT_HISTORICAL_VOLATILITY,
    RISK_FACT_OFFICIAL_RISK_VALUE,
    SUKUK_ETF_WEIGHTS,
    SUKUK_PARTICIPATION_FUND_WEIGHTS,
    TURKISH_FI_PROFILES,
)
from services.nabi_score_v4 import inverse, scale
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
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
    vehicle = str(mandate.vehicle or "").strip() if mandate else ""
    if vehicle in TURKISH_FI_PROFILES:
        return vehicle
    layer = str(mandate.primary_layer or "").strip().lower() if mandate else ""
    region = str(mandate.region or "").strip().upper() if mandate else ""
    if region == "TR":
        if layer == "real_estate":
            return PROFILE_REAL_ESTATE_PARTICIPATION_FUND
        if layer == "multi_asset":
            return PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND
    if layer == "sukuk":
        return PROFILE_SUKUK_ETF
    if layer == "real_estate":
        return PROFILE_REIT_ETF
    if layer == "precious_metals":
        return PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND
    return PROFILE_EQUITY_ETF


def weights_for_profile(profile: str, *, region: str = "") -> dict[str, float]:
    if profile == PROFILE_LIQUIDITY_PARTICIPATION_FUND:
        return dict(LIQUIDITY_PARTICIPATION_FUND_WEIGHTS)
    if profile == PROFILE_EQUITY_PARTICIPATION_FUND:
        return dict(EQUITY_PARTICIPATION_FUND_WEIGHTS)
    if profile == PROFILE_SUKUK_PARTICIPATION_FUND:
        return dict(SUKUK_PARTICIPATION_FUND_WEIGHTS)
    if profile == PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND:
        return dict(PRECIOUS_METALS_PARTICIPATION_FUND_WEIGHTS)
    if profile == PROFILE_REAL_ESTATE_PARTICIPATION_FUND:
        return dict(REAL_ESTATE_PARTICIPATION_FUND_WEIGHTS)
    if profile == PROFILE_MIXED_MULTI_ASSET_PARTICIPATION_FUND:
        return dict(MIXED_MULTI_ASSET_PARTICIPATION_FUND_WEIGHTS)
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


def _management_fee_score(management_fee_pct: Optional[float]) -> Optional[float]:
    """KAP management fee only. Mutual-fund band, not ETF TER 0.15–0.80."""
    if management_fee_pct is None:
        return None
    return inverse(management_fee_pct, MANAGEMENT_FEE_GOOD_PCT, MANAGEMENT_FEE_BAD_PCT)


def _concentration_score(top_weight: Optional[float], top10: Optional[float]) -> Optional[float]:
    if top_weight is None:
        return None
    single = inverse(top_weight, 5.0, 40.0)
    if top10 is None:
        return single
    return (single + inverse(top10, 25.0, 90.0)) / 2.0


def _diversification_score(
    count: Optional[int],
    unknown_pct: Optional[float],
    *,
    effective_holdings: Optional[float] = None,
) -> Optional[float]:
    """Score from official weights. Raw count cannot override a concentrated HHI."""
    if effective_holdings is not None:
        base = scale(effective_holdings, DIVERSIFICATION_EFFECTIVE_N_BAD, DIVERSIFICATION_EFFECTIVE_N_GOOD)
        if (
            count is not None
            and count >= LARGE_COUNT_FOR_HHI_OVERRIDE
            and effective_holdings < CONCENTRATED_EFFECTIVE_N
        ):
            base = scale(effective_holdings, DIVERSIFICATION_EFFECTIVE_N_BAD, DIVERSIFICATION_EFFECTIVE_N_GOOD)
    elif count is not None:
        base = scale(float(count), 15.0, 120.0)
    else:
        return None
    if unknown_pct is None:
        return base
    return max(0.0, base - min(unknown_pct, 40.0))


def _liquidity_score(net_assets: Optional[float]) -> Optional[float]:
    if net_assets is None:
        return None
    return scale(net_assets / 1_000_000.0, 50.0, 2500.0)


def _lookthrough_ready(lookthrough: Optional[FundLookthroughSummary]) -> bool:
    return lookthrough is not None and lookthrough.holdings_count > 0


def _country_dimension(exposure: Optional[FundExposureEvidence]) -> FundDimensionResult:
    if exposure is not None and exposure.country_reliable:
        return _ready(
            DIM_COUNTRY_CONCENTRATION,
            _concentration_score(exposure.largest_country_weight, exposure.top5_country_weight),
            "nport_invCountry",
        )
    return _ready(DIM_COUNTRY_CONCENTRATION, None, "official_country")


def _denomination_and_style_dims(exposure: Optional[FundExposureEvidence]) -> list[FundDimensionResult]:
    if exposure is not None and exposure.denomination_present:
        denomination = _ready(
            DIM_CURRENCY_DENOMINATION,
            None,
            "nport_curCd",
            "not_fx_exposure",
        )
    else:
        denomination = _missing(DIM_CURRENCY_DENOMINATION, "official_denomination")
    return [
        denomination,
        _missing(DIM_DEVELOPED_EMERGING, "official_developed_emerging"),
    ]


def _tracking_dimension(performance: Optional[OfficialFundPerformance]) -> FundDimensionResult:
    if (
        performance is None
        or performance.tracking_difference is None
        or performance.tracking_concept != "TRACKING_DIFFERENCE"
    ):
        return _missing(DIM_TRACKING_EVAL, "official_period_tracking_difference")
    return _ready(
        DIM_TRACKING_EVAL,
        inverse(abs(performance.tracking_difference), 0.25, 5.0),
        "tracking_difference",
        performance.tracking_horizon or "matched_period",
    )


def evaluate_official_fund_intelligence(
    symbol: str,
    *,
    provider: Optional[object] = None,
    lookthrough: Optional[FundLookthroughSummary] = None,
    performance: Optional[OfficialFundPerformance] = None,
    official_yield: Optional[OfficialFundYield] = None,
    historical_performance_present: bool = False,
    official_risk_series_present: bool = False,
    fixed_income: Optional[FundFixedIncomeRiskEvidence] = None,
    use_official_fixed_income: bool = True,
    exposure: Optional[FundExposureEvidence] = None,
) -> FundIntelligenceEvaluation:
    fund = str(symbol or "").strip().upper()
    resolved = provider or _default_official_provider(fund)
    nav_performance = performance
    if nav_performance is None and hasattr(resolved, "performance"):
        nav_performance = resolved.performance(fund)
    yield_evidence = official_yield
    if yield_evidence is None and hasattr(resolved, "sec_yield"):
        yield_evidence = resolved.sec_yield(fund)
    lookthrough_view = lookthrough
    official_issuer_present = False
    if lookthrough_view is None and hasattr(resolved, "holdings"):
        holdings_file = resolved.holdings(fund)
        if holdings_file is not None:
            lookthrough_view = build_fund_lookthrough_summary(holdings_file)
            from services.fund_lookthrough_summary import official_issuer_field_present

            official_issuer_present = official_issuer_field_present(holdings_file)
    fi_view = fixed_income
    if fi_view is None and use_official_fixed_income and hasattr(resolved, "fixed_income_risk"):
        fi_view = resolved.fixed_income_risk(fund)
    if fi_view is not None and fi_view.official_issuer_field_present:
        official_issuer_present = True
    exposure_view = exposure
    if exposure_view is None and hasattr(resolved, "exposure"):
        exposure_view = resolved.exposure(fund)
    maturity_ready = False
    maturity_days = None
    issuer_largest = None
    issuer_top10 = None
    issuer_ready = official_issuer_present
    if hasattr(resolved, "pdr_holdings"):
        pdr_file = resolved.pdr_holdings(fund)
        if pdr_file is not None:
            from services.official_kap_pdr import (
                issuer_concentration_stats,
                pdr_lookthrough_readiness,
                weighted_average_maturity_days,
            )

            ready = pdr_lookthrough_readiness(pdr_file)
            maturity_ready = ready.maturity_ready
            issuer_ready = issuer_ready or ready.issuer_concentration_ready
            maturity_days = weighted_average_maturity_days(pdr_file)
            issuer_largest, issuer_top10, _ = issuer_concentration_stats(pdr_file)
    return evaluate_fund_intelligence(
        facts=resolved.facts(fund),
        mandate=resolved.mandate(fund),
        sharia=resolved.sharia_evidence(fund),
        purification=resolved.purification_evidence(fund),
        lookthrough=lookthrough_view,
        performance=nav_performance,
        official_yield=yield_evidence,
        historical_performance_present=historical_performance_present,
        official_risk_series_present=official_risk_series_present,
        official_issuer_present=official_issuer_present,
        fixed_income=fi_view,
        exposure=exposure_view,
        official_country_weights=bool(exposure_view is not None and exposure_view.country_reliable),
        maturity_ready=maturity_ready,
        maturity_days=maturity_days,
        issuer_largest_weight=issuer_largest,
        issuer_top10_weight=issuer_top10,
        issuer_concentration_ready=issuer_ready,
    )


def _default_official_provider(symbol: str):
    from services.official_tefas_product import default_tefas_fund_provider

    tefas = default_tefas_fund_provider()
    if tefas.supports(symbol):
        return tefas
    from services.official_sp_funds_product import default_official_sp_funds_provider

    return default_official_sp_funds_provider()


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
    official_yield: Optional[OfficialFundYield] = None,
    official_issuer_present: bool = False,
    fixed_income: Optional[FundFixedIncomeRiskEvidence] = None,
    exposure: Optional[FundExposureEvidence] = None,
    maturity_ready: bool = False,
    maturity_days: Optional[float] = None,
    issuer_largest_weight: Optional[float] = None,
    issuer_top10_weight: Optional[float] = None,
    issuer_concentration_ready: bool = False,
) -> FundIntelligenceEvaluation:
    if official_yield is not None and official_yield.sec_yield_30d is not None:
        official_yield_present = True
    if performance is not None:
        historical_performance_present = historical_performance_present or performance.has_return_history()
        official_risk_series_present = official_risk_series_present or performance.has_risk_history()
    profile = profile_for_mandate(mandate)
    region = mandate.region if mandate else ""
    scored_weights = weights_for_profile(profile, region=region)
    participation = evaluate_fund_participation_gate(sharia)
    turkish_kontrol = (
        profile in TURKISH_FI_PROFILES
        and sharia is not None
        and sharia.participation_status == PARTICIPATION_STATUS_KONTROL_ET
        and bool(sharia.official_mandate_present)
        and participation.status != "ADVERSE"
    )
    if participation.eligible:
        dimensions = [_ready(DIM_PARTICIPATION_MANDATE, None, "official_sharia")]
    elif turkish_kontrol:
        dimensions = [
            FundDimensionResult(
                name=DIM_PARTICIPATION_MANDATE,
                status=DIM_STATUS_READY,
                score=None,
                confidence=0.6,
                facts_used=("official_kap_participation_wording",),
                reason_codes=("PARTICIPATION_KONTROL_ET",),
            )
        ]
    else:
        dimensions = [
            FundDimensionResult(
                name=DIM_PARTICIPATION_MANDATE,
                status=DIM_STATUS_MISSING if participation.status != "ADVERSE" else DIM_STATUS_READY,
                missing_facts=() if participation.eligible else ("official_sharia",),
                reason_codes=(participation.limitation,) if participation.limitation else (),
            )
        ]
    if historical_performance_present:
        lead, horizon = (None, None) if performance is None else performance.performance_lead()
        perf_score = None
        if lead is not None:
            perf_score = scale(lead, -15.0, 20.0)
        dimensions.append(_ready(DIM_PERFORMANCE_EVAL, perf_score, horizon or "official_nav_return"))
    else:
        dimensions.append(_missing(DIM_PERFORMANCE_EVAL, "official_return_history"))
    momentum_profiles = {PROFILE_EQUITY_ETF, PROFILE_REIT_ETF, PROFILE_EQUITY_PARTICIPATION_FUND}
    if profile in momentum_profiles:
        if performance is not None:
            momentum, momentum_horizon = performance.momentum_lead()
        else:
            momentum, momentum_horizon = None, None
        if momentum is not None:
            dimensions.append(
                _ready(DIM_MOMENTUM_EVAL, scale(momentum, -8.0, 8.0), momentum_horizon or "official_short_horizon")
            )
        else:
            dimensions.append(_missing(DIM_MOMENTUM_EVAL, "official_short_horizon"))
    if official_risk_series_present:
        risk_score = None
        risk_facts = []
        if performance is not None:
            metric = performance.drawdown if performance.drawdown is not None else performance.volatility
            if performance.drawdown is not None:
                risk_facts.append(RISK_FACT_HISTORICAL_MAX_DRAWDOWN)
            if performance.volatility is not None:
                risk_facts.append(RISK_FACT_HISTORICAL_VOLATILITY)
            if performance.official_risk_value is not None:
                risk_facts.append(RISK_FACT_OFFICIAL_RISK_VALUE)
            if metric is not None:
                # RISK score uses historical drawdown, else historical volatility.
                # TEFAS official_risk_value is stored, never substituted.
                risk_score = inverse(abs(metric), 8.0, 40.0)
        dimensions.append(_ready(DIM_RISK_EVAL, risk_score, *(risk_facts or ("official_drawdown",))))
    else:
        dimensions.append(_missing(DIM_RISK_EVAL, "official_drawdown_series"))
    if facts.expense_ratio is not None:
        if profile in TURKISH_FI_PROFILES:
            dimensions.append(
                _ready(DIM_COST_EVAL, _management_fee_score(facts.expense_ratio), "kap_management_fee")
            )
        else:
            dimensions.append(_ready(DIM_COST_EVAL, _cost_score(facts.expense_ratio), "expense_ratio"))
    else:
        dimensions.append(_missing(DIM_COST_EVAL, "expense_ratio" if profile not in TURKISH_FI_PROFILES else "kap_management_fee"))
    if _lookthrough_ready(lookthrough) and holdings_reliable(lookthrough):
        dimensions.append(
            _ready(
                DIM_DIVERSIFICATION_EVAL,
                _diversification_score(
                    lookthrough.holdings_count,
                    lookthrough.unknown_weight_pct,
                    effective_holdings=lookthrough.effective_holdings,
                ),
                "effective_holdings" if lookthrough.effective_holdings is not None else "holdings_count",
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
    elif _lookthrough_ready(lookthrough):
        dimensions.append(_missing(DIM_DIVERSIFICATION_EVAL, "unknown_or_unreconciled_weights"))
        dimensions.append(_missing(DIM_CONCENTRATION_EVAL, "unknown_or_unreconciled_weights"))
    else:
        dimensions.append(_missing(DIM_DIVERSIFICATION_EVAL, "official_holdings"))
        dimensions.append(_missing(DIM_CONCENTRATION_EVAL, "official_holdings"))
    if facts.net_assets is not None and facts.market_price is not None:
        dimensions.append(_ready(DIM_LIQUIDITY_EVAL, _liquidity_score(facts.net_assets), "net_assets", "market_price"))
    else:
        dimensions.append(_missing(DIM_LIQUIDITY_EVAL, "net_assets", "market_price"))
    tracking = _tracking_dimension(performance)
    if profile in TURKISH_FI_PROFILES:
        dimensions.append(_na(DIM_TRACKING_EVAL, "NO_OFFICIAL_TRACKING_DIFFERENCE"))
        dimensions.append(_na(DIM_COUNTRY_CONCENTRATION, "COUNTRY_NOT_IN_OFFICIAL_PDR"))
        dimensions.append(_na(DIM_CURRENCY_EXPOSURE, "FX_NOT_IN_OFFICIAL_PDR"))
        dimensions.append(_na(DIM_CURRENCY_DENOMINATION, "OPTIONAL_TURKISH_FUND"))
        dimensions.append(_na(DIM_DEVELOPED_EMERGING, "OPTIONAL_TURKISH_FUND"))
        dimensions.append(_na(DIM_YIELD, "NO_OFFICIAL_YIELD"))
        dimensions.append(_na(DIM_CREDIT_QUALITY, "CREDIT_NOT_INFERRED"))
        dimensions.append(_na(DIM_DURATION, "USE_MATURITY_NOT_DURATION"))
        dimensions.append(_na(DIM_RATE_RISK, "NO_OFFICIAL_DV01"))
        dimensions.append(_na(DIM_CREDIT_RISK, "NO_OFFICIAL_CREDIT_SPREAD"))
        dimensions.append(_na(DIM_REAL_ESTATE_CONCENTRATION, "NOT_REIT"))
        if profile in {PROFILE_LIQUIDITY_PARTICIPATION_FUND, PROFILE_SUKUK_PARTICIPATION_FUND}:
            if maturity_ready:
                maturity_score = None
                if profile == PROFILE_LIQUIDITY_PARTICIPATION_FUND and maturity_days is not None:
                    maturity_score = inverse(maturity_days, 5.0, 45.0)
                dimensions.append(
                    _ready(
                        DIM_MATURITY,
                        maturity_score,
                        "official_pdr_maturity_date",
                        "kap_wam_45_day_cap" if maturity_score is not None else "maturity_coverage",
                    )
                )
            else:
                dimensions.append(_missing(DIM_MATURITY, "official_pdr_maturity_date"))
        elif profile == PROFILE_PRECIOUS_METALS_PARTICIPATION_FUND:
            dimensions.append(_na(DIM_MATURITY, "PRECIOUS_METALS_PARTICIPATION_PROFILE"))
        else:
            dimensions.append(_na(DIM_MATURITY, "EQUITY_PARTICIPATION_PROFILE"))
        if profile == PROFILE_SUKUK_PARTICIPATION_FUND:
            if issuer_concentration_ready and issuer_largest_weight is not None:
                dimensions.append(
                    _ready(
                        DIM_ISSUER_CONCENTRATION,
                        _concentration_score(issuer_largest_weight, issuer_top10_weight),
                        "official_pdr_issuer",
                    )
                )
            else:
                dimensions.append(_missing(DIM_ISSUER_CONCENTRATION, "official_pdr_issuer"))
        else:
            dimensions.append(_na(DIM_ISSUER_CONCENTRATION, "NOT_SUKUK_PARTICIPATION"))
    elif profile == PROFILE_EQUITY_ETF:
        dimensions.append(tracking)
        if region == "US":
            dimensions.append(_na(DIM_COUNTRY_CONCENTRATION, "US_EQUITY_PROFILE"))
            dimensions.append(_na(DIM_CURRENCY_EXPOSURE, "US_EQUITY_PROFILE"))
            dimensions.append(_na(DIM_CURRENCY_DENOMINATION, "US_EQUITY_PROFILE"))
            dimensions.append(_na(DIM_DEVELOPED_EMERGING, "US_EQUITY_PROFILE"))
        elif official_country_weights:
            dimensions.append(_country_dimension(exposure))
        else:
            dimensions.append(_missing(DIM_COUNTRY_CONCENTRATION, "official_country_weights"))
        if region != "US":
            if official_currency_weights:
                dimensions.append(_ready(DIM_CURRENCY_EXPOSURE, None, "official_fx_exposure"))
            else:
                dimensions.append(_missing(DIM_CURRENCY_EXPOSURE, "official_fx_exposure"))
            dimensions.extend(_denomination_and_style_dims(exposure))
        dimensions.append(_na(DIM_DURATION, "NOT_SUKUK"))
        dimensions.append(_na(DIM_YIELD, "NOT_SUKUK"))
        dimensions.append(_na(DIM_CREDIT_QUALITY, "NOT_SUKUK"))
        dimensions.append(_na(DIM_ISSUER_CONCENTRATION, "NOT_SUKUK"))
        dimensions.append(_na(DIM_RATE_RISK, "NOT_SUKUK"))
        dimensions.append(_na(DIM_CREDIT_RISK, "NOT_SUKUK"))
        dimensions.append(_na(DIM_REAL_ESTATE_CONCENTRATION, "NOT_REIT"))
    elif profile == PROFILE_SUKUK_ETF:
        dimensions.append(tracking if tracking.status != DIM_STATUS_MISSING else _na(DIM_TRACKING_EVAL, "SUKUK_PROFILE"))
        dimensions.append(_na(DIM_COUNTRY_CONCENTRATION, "SUKUK_PROFILE"))
        dimensions.append(_na(DIM_CURRENCY_EXPOSURE, "SUKUK_PROFILE"))
        dimensions.append(_na(DIM_CURRENCY_DENOMINATION, "SUKUK_PROFILE"))
        dimensions.append(_na(DIM_DEVELOPED_EMERGING, "SUKUK_PROFILE"))
        dimensions.append(_na(DIM_REAL_ESTATE_CONCENTRATION, "NOT_REIT"))
        if official_duration_present:
            dimensions.append(_ready(DIM_DURATION, None, "official_duration"))
        else:
            dimensions.append(_missing(DIM_DURATION, "official_duration"))
        if fixed_income is not None and fixed_income.rate_risk_present:
            dimensions.append(_ready(DIM_RATE_RISK, None, "nport_dv01_dv100", "dv01_is_not_duration"))
        else:
            dimensions.append(_missing(DIM_RATE_RISK, "official_interest_rate_risk"))
        if fixed_income is not None and fixed_income.credit_spread_present:
            dimensions.append(_ready(DIM_CREDIT_RISK, None, "nport_credit_spread", "spread_is_not_rating"))
        else:
            dimensions.append(_missing(DIM_CREDIT_RISK, "official_credit_spread"))
        yield_score = None
        if official_yield is not None and official_yield.sec_yield_30d is not None:
            yield_score = scale(official_yield.sec_yield_30d, 1.0, 6.0)
        dimensions.append(
            _ready(DIM_YIELD, yield_score, "sec_30_day_yield")
            if official_yield_present
            else _missing(DIM_YIELD, "official_yield")
        )
        dimensions.append(
            _ready(DIM_CREDIT_QUALITY, None, "official_credit")
            if official_credit_present
            else _missing(DIM_CREDIT_QUALITY, "official_credit")
        )
        if fixed_income is not None:
            if fixed_income.issuer_reliable:
                dimensions.append(
                    _ready(
                        DIM_ISSUER_CONCENTRATION,
                        _concentration_score(
                            fixed_income.largest_issuer_weight,
                            fixed_income.top10_issuer_weight,
                        ),
                        "nport_issuer_name",
                    )
                )
            else:
                dimensions.append(_missing(DIM_ISSUER_CONCENTRATION, "nport_issuer_name"))
        elif official_issuer_present and _lookthrough_ready(lookthrough) and holdings_reliable(lookthrough):
            dimensions.append(
                _ready(
                    DIM_ISSUER_CONCENTRATION,
                    _concentration_score(lookthrough.single_name_concentration_pct, None),
                    "official_issuer",
                )
            )
        else:
            dimensions.append(_missing(DIM_ISSUER_CONCENTRATION, "official_issuer_field"))
    else:
        dimensions.append(tracking if tracking.status != DIM_STATUS_MISSING else _na(DIM_TRACKING_EVAL, "REIT_PROFILE"))
        dimensions.append(_na(DIM_DURATION, "NOT_SUKUK"))
        dimensions.append(_na(DIM_YIELD, "NOT_SUKUK"))
        dimensions.append(_na(DIM_CREDIT_QUALITY, "NOT_SUKUK"))
        dimensions.append(_na(DIM_ISSUER_CONCENTRATION, "NOT_SUKUK"))
        dimensions.append(_na(DIM_RATE_RISK, "NOT_SUKUK"))
        dimensions.append(_na(DIM_CREDIT_RISK, "NOT_SUKUK"))
        if official_real_estate_weights:
            dimensions.append(_ready(DIM_REAL_ESTATE_CONCENTRATION, None, "official_re_weights"))
        else:
            dimensions.append(
                FundDimensionResult(
                    name=DIM_REAL_ESTATE_CONCENTRATION,
                    status=DIM_STATUS_MISSING,
                    missing_facts=("official_property_sector_or_geo",),
                    reason_codes=(
                        "OFFICIAL_EVIDENCE_MISSING",
                        "SECURITY_LEVEL_USES_CONCENTRATION",
                    ),
                )
            )
        if official_country_weights:
            dimensions.append(_country_dimension(exposure))
        else:
            dimensions.append(_missing(DIM_COUNTRY_CONCENTRATION, "official_country_weights"))
        dimensions.append(_na(DIM_CURRENCY_EXPOSURE, "OPTIONAL_REIT"))
        dimensions.extend(_denomination_and_style_dims(exposure))
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
    evidence_threshold_met = (
        len(ready_scored) >= MIN_READY_SCORED_DIMENSIONS
        and coverage >= MIN_READY_WEIGHT_COVERAGE
        and return_risk_ready
    )
    threshold_met = (participation.eligible or turkish_kontrol) and evidence_threshold_met
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
    if threshold_met:
        confidence = min(1.0, coverage)
    elif participation.eligible:
        confidence = min(coverage, 0.45)
    provenance = (
        "official_tefas_kap" if profile in TURKISH_FI_PROFILES else "official_sp_funds_product",
        "official_fund_holdings" if lookthrough is not None else "product_facts_only",
        "official_nport_fixed_income" if fixed_income is not None else "nport_fixed_income_absent",
        "official_nport_exposure" if exposure is not None else "nport_exposure_absent",
        "purification_metadata_only",
    )
    as_of = facts.as_of or facts.holdings_as_of
    if as_of is None and performance is not None:
        as_of = performance.as_of
    return FundIntelligenceEvaluation(
        symbol=facts.symbol,
        fund_type_profile=profile,
        state=state,
        score=None if not threshold_met else (None if score is None else round(score, 2)),
        confidence=round(confidence, 4),
        as_of=as_of,
        facts_version=FUND_EVAL_FACTS_VERSION,
        engine_version=FUND_EVAL_ENGINE_VERSION,
        provenance=provenance,
        dimensions=tuple(dimensions),
        participation=participation,
        missing_evidence=missing_evidence,
        publishable=participation.eligible and state != STATE_INSUFFICIENT_DATA,
        purification_factor_pct=None if purification is None else purification.latest_factor_pct,
        purification_required=None if purification is None else purification.purification_required,
        completeness=round(coverage, 4),
    )
