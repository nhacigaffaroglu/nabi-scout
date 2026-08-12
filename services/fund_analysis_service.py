from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from config.participation_catalog import CONFIGURED_PARTICIPATION_CATALOG
from services.alpha_vantage_adapter import (
    alpha_daily_rows,
    normalize_alpha_expense_ratio,
    normalize_alpha_yield_pct,
    parse_alpha_holdings,
    parse_alpha_sector_weights,
)
from services.alpha_vantage_cache import AlphaVantageFundCache, get_fund_cache
from services.alpha_vantage_client import (
    STATUS_AUTH,
    STATUS_MALFORMED,
    STATUS_NETWORK,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_PREMIUM_REQUIRED,
    STATUS_RATE_LIMIT,
    AlphaVantageClient,
    AlphaVantageError,
    alpha_error_status,
)
from services.fund_analysis_contract import (
    ANALYSIS_KIND_FUND,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DATA_PROVIDER_ALPHA_VANTAGE,
    DIMENSION_CONCENTRATION,
    DIMENSION_COST,
    DIMENSION_DATA_QUALITY,
    DIMENSION_LIQUIDITY,
    FundAnalysisResult,
    FundDimensionScore,
    FundPerformanceMetrics,
    FundRiskMetrics,
    LABEL_CONFIGURED_PARTICIPATION,
    LABEL_INCELEME_UYGUN,
    LABEL_VERI_YETERSIZ,
    LABEL_YOGUNLASMA_RISKI,
    LABEL_YUKSEK_MALIYET,
    PARTICIPATION_SOURCE_CONFIGURED,
)
from services.fund_performance_service import (
    compute_fund_performance_metrics,
    compute_fund_risk_metrics,
    normalize_price_points,
)
from services.participation_intelligence_service import (
    get_participation_assessment_for_fund,
)
from services.symbol_resolver_service import ResolvedSecurity, participation_for_symbol

EXPENSE_HIGH_THRESHOLD_PCT = 0.50
TOP10_CONCENTRATION_RISK_THRESHOLD_PCT = 50.0
MIN_COMPLETENESS_FOR_DIMENSIONS = 50.0
MIN_COMPLETENESS_INCELEME = 60.0
MIN_COMPLETENESS_VERI_YETERSIZ = 40.0

AUM_LIQUIDITY_TIERS = (
    (10_000_000_000, 90.0),
    (1_000_000_000, 75.0),
    (100_000_000, 60.0),
    (10_000_000, 45.0),
)

VOLUME_LIQUIDITY_TIERS = (
    (5_000_000, 90.0),
    (1_000_000, 75.0),
    (250_000, 60.0),
    (50_000, 45.0),
)

HISTORY_SKIP_STATUSES = {STATUS_AUTH}


def analyze_fund(
    resolved: ResolvedSecurity,
    *,
    alpha_vantage_client: AlphaVantageClient,
    alpha_cache: Optional[AlphaVantageFundCache] = None,
) -> FundAnalysisResult:
    cache = alpha_cache if alpha_cache is not None else get_fund_cache()
    symbol = resolved.symbol
    endpoint_status: Dict[str, str] = {}
    warnings: List[str] = []
    unsupported_fields: List[str] = []
    performance_warnings: List[str] = []

    profile_payload, endpoint_status["alpha_etf_profile"], profile_warning = _safe_alpha_call(
        alpha_vantage_client,
        "etf_profile",
        symbol,
        cache=cache,
    )
    if profile_warning:
        warnings.append(profile_warning)

    fund_name = _first_text(
        profile_payload.get("description"),
        profile_payload.get("name"),
        resolved.company_name,
        symbol,
    )
    exchange = resolved.exchange
    asset_class = _first_text(profile_payload.get("asset_class"), profile_payload.get("category"))
    domicile = None
    benchmark = None
    inception_date = _first_text(profile_payload.get("inception_date"))

    expense_ratio = normalize_alpha_expense_ratio(profile_payload.get("net_expense_ratio"))
    if (
        expense_ratio is None
        and profile_payload.get("net_expense_ratio") not in (None, "")
    ):
        unsupported_fields.append("expense_ratio")

    distribution_yield = normalize_alpha_yield_pct(profile_payload.get("dividend_yield"))
    aum = _as_positive_float(profile_payload.get("net_assets"))

    parsed_holdings = parse_alpha_holdings(profile_payload.get("holdings"))
    holdings_count = len(profile_payload.get("holdings") or []) or (
        len(parsed_holdings) if parsed_holdings else None
    )
    top_holdings = parsed_holdings[:10]
    top10_concentration_pct = _top10_concentration(top_holdings)
    sector_weights = parse_alpha_sector_weights(profile_payload.get("sectors"))

    participation_status, participation_score = participation_for_symbol(symbol)
    participation_source = (
        PARTICIPATION_SOURCE_CONFIGURED
        if symbol in CONFIGURED_PARTICIPATION_CATALOG
        else None
    )
    participation_assessment = get_participation_assessment_for_fund(symbol)

    performance_metrics: Optional[FundPerformanceMetrics] = None
    risk_metrics: Optional[FundRiskMetrics] = None
    price_history_status: Optional[str] = None
    current_price: Optional[float] = None
    volume: Optional[float] = None
    avg_volume: Optional[float] = None

    profile_status = endpoint_status.get("alpha_etf_profile", "UNAVAILABLE")
    if _should_fetch_alpha_history(profile_status):
        history_payload, endpoint_status["alpha_time_series_daily"], history_warning = (
            _safe_alpha_call(
                alpha_vantage_client,
                "time_series_daily",
                symbol,
                cache=cache,
                outputsize="compact",
            )
        )
        if history_warning:
            performance_warnings.append(history_warning)
            warnings.append(history_warning)

        history_status = endpoint_status.get("alpha_time_series_daily", "UNAVAILABLE")
        price_history_status = history_status
        if history_status == STATUS_OK:
            history_rows = alpha_daily_rows(history_payload)
            series = normalize_price_points(
                symbol,
                history_rows,
                source="alpha_vantage_time_series_daily",
            )
            if series.points:
                as_of = date.today()
                performance = compute_fund_performance_metrics(series, as_of=as_of)
                risk = compute_fund_risk_metrics(series, asset_class=asset_class)
                combined_warnings = list(performance.warnings)
                combined_warnings.extend(performance_warnings)
                performance_metrics = _build_performance_metrics_with_coverage(
                    performance,
                    series=series,
                    combined_warnings=combined_warnings,
                )
                risk_metrics = risk
                performance_warnings = combined_warnings
                latest = series.points[-1]
                current_price = latest.close
                volume = latest.volume
            else:
                performance_warnings.append("Fiyat geçmişi boş veya geçersiz.")
                price_history_status = "EMPTY"
        elif history_status == STATUS_RATE_LIMIT:
            performance_warnings.append(
                "Fiyat geçmişi sağlayıcı limiti nedeniyle alınamadı."
            )
        elif history_status == STATUS_PREMIUM_REQUIRED:
            performance_warnings.append(
                "Fiyat geçmişi mevcut plan kapsamında erişilemedi."
            )
    else:
        price_history_status = profile_status
        if profile_status == STATUS_PREMIUM_REQUIRED:
            performance_warnings.append(
                "Alpha Vantage ETF profili mevcut plan kapsamında erişilemedi."
            )
        elif profile_status == STATUS_RATE_LIMIT:
            performance_warnings.append(
                "Alpha Vantage rate limit nedeniyle ETF profili alınamadı."
            )

    warnings.extend(performance_warnings)

    completeness = _compute_completeness(
        fund_name=fund_name,
        exchange=exchange,
        benchmark=benchmark,
        expense_ratio=expense_ratio,
        aum=aum,
        current_price=current_price,
        holdings_count=holdings_count,
        top_holdings=top_holdings,
    )
    confidence = _analysis_confidence(completeness, endpoint_status)
    dimension_scores = _build_dimension_scores(
        completeness=completeness,
        expense_ratio=expense_ratio,
        aum=aum,
        volume=volume,
        avg_volume=avg_volume,
        top10_concentration_pct=top10_concentration_pct,
    )
    labels = _build_labels(
        completeness=completeness,
        expense_ratio=expense_ratio,
        top10_concentration_pct=top10_concentration_pct,
        participation_source=participation_source,
    )

    return FundAnalysisResult(
        symbol=symbol,
        analysis_kind=ANALYSIS_KIND_FUND,
        fund_name=fund_name,
        issuer=None,
        exchange=exchange,
        asset_class=asset_class,
        domicile=domicile,
        benchmark=benchmark,
        inception_date=inception_date,
        holdings_count=holdings_count,
        top_holdings=top_holdings,
        top10_concentration_pct=top10_concentration_pct,
        sector_weights=sector_weights,
        expense_ratio=expense_ratio,
        distribution_yield=distribution_yield,
        aum=aum,
        current_price=current_price,
        volume=volume,
        avg_volume=avg_volume,
        participation_status=participation_status,
        participation_score=participation_score,
        participation_source=participation_source,
        participation_assessment=participation_assessment,
        data_completeness_pct=completeness,
        analysis_confidence=confidence,
        data_provider=DATA_PROVIDER_ALPHA_VANTAGE,
        endpoint_status=endpoint_status,
        warnings=warnings,
        unsupported_fields=unsupported_fields,
        dimension_scores=dimension_scores,
        labels=labels,
        performance_metrics=performance_metrics,
        risk_metrics=risk_metrics,
        price_history_status=price_history_status,
        performance_warnings=performance_warnings,
    )


def _should_fetch_alpha_history(profile_status: str) -> bool:
    if profile_status in HISTORY_SKIP_STATUSES:
        return False
    return True


def _build_performance_metrics_with_coverage(
    performance: FundPerformanceMetrics,
    *,
    series,
    combined_warnings: List[str],
) -> FundPerformanceMetrics:
    history_is_full_year = performance.return_1y_full_confidence is True
    return_1y_pct = performance.return_1y_pct if history_is_full_year else None
    return FundPerformanceMetrics(
        return_1m_pct=performance.return_1m_pct,
        return_ytd_pct=performance.return_ytd_pct,
        return_1y_pct=return_1y_pct,
        observation_count=performance.observation_count,
        is_stale=performance.is_stale,
        return_1y_full_confidence=history_is_full_year if return_1y_pct is not None else False,
        history_start_date=series.points[0].date.isoformat() if series.points else None,
        history_end_date=series.points[-1].date.isoformat() if series.points else None,
        history_is_full_year=history_is_full_year,
        warnings=tuple(combined_warnings),
    )


def _safe_alpha_call(
    client: AlphaVantageClient,
    method_name: str,
    symbol: str,
    *,
    cache: Optional[AlphaVantageFundCache] = None,
    **kwargs: str,
) -> Tuple[Dict[str, Any], str, Optional[str]]:
    if cache is not None:
        cached = cache.get(method_name, symbol, **kwargs)
        if cached is not None:
            warning = None if cached.status == STATUS_OK else _warning_for_alpha(
                method_name,
                cached.status,
            )
            return cached.payload, cached.status, warning

    method = getattr(client, method_name)
    try:
        payload = method(symbol, **kwargs) if kwargs else method(symbol)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            result = ({}, STATUS_MALFORMED, _warning_for_alpha(method_name, STATUS_MALFORMED))
            if cache is not None:
                cache.set(method_name, symbol, result[0], result[1], **kwargs)
            return result
        if cache is not None:
            cache.set(method_name, symbol, payload, STATUS_OK, **kwargs)
        return payload, STATUS_OK, None
    except AlphaVantageError as exc:
        status = alpha_error_status(exc)
        warning = _warning_for_alpha(method_name, status)
        if cache is not None:
            cache.set(method_name, symbol, {}, status, **kwargs)
        return {}, status, warning


def _warning_for_alpha(method_name: str, status: str) -> Optional[str]:
    if status == STATUS_RATE_LIMIT:
        return f"Alpha Vantage {method_name}: rate limit nedeniyle veri alınamadı."
    if status == STATUS_PREMIUM_REQUIRED:
        return f"Alpha Vantage {method_name}: mevcut plan kapsamında erişilemedi."
    if status == STATUS_AUTH:
        return f"Alpha Vantage {method_name}: kimlik doğrulama hatası."
    if status == STATUS_NOT_FOUND:
        return f"Alpha Vantage {method_name}: sembol bulunamadı."
    if status == STATUS_MALFORMED:
        return f"Alpha Vantage {method_name}: beklenmeyen yanıt."
    if status == STATUS_NETWORK:
        return f"Alpha Vantage {method_name}: ağ hatası."
    return None


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _as_positive_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _top10_concentration(holdings) -> Optional[float]:
    if not holdings:
        return None
    weights = [holding.weight_pct for holding in holdings[:10] if holding.weight_pct is not None]
    if not weights:
        return None
    return round(sum(weights), 2)


def _compute_completeness(
    *,
    fund_name: Optional[str],
    exchange: Optional[str],
    benchmark: Optional[str],
    expense_ratio: Optional[float],
    aum: Optional[float],
    current_price: Optional[float],
    holdings_count: Optional[int],
    top_holdings,
) -> float:
    checks = {
        "fund_name": bool(fund_name),
        "exchange": bool(exchange),
        "benchmark": bool(benchmark),
        "expense_ratio": expense_ratio is not None,
        "aum": aum is not None,
        "current_price": current_price is not None,
        "holdings": bool(top_holdings) or holdings_count is not None,
    }
    present = sum(1 for value in checks.values() if value)
    return round(present / len(checks) * 100, 1)


def _analysis_confidence(
    completeness: float,
    endpoint_status: Dict[str, str],
) -> str:
    profile_ok = endpoint_status.get("alpha_etf_profile") == STATUS_OK
    history_ok = endpoint_status.get("alpha_time_series_daily") == STATUS_OK
    if completeness >= 75 and profile_ok and history_ok:
        return CONFIDENCE_HIGH
    if completeness >= 50 and profile_ok:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _build_dimension_scores(
    *,
    completeness: float,
    expense_ratio: Optional[float],
    aum: Optional[float],
    volume: Optional[float],
    avg_volume: Optional[float],
    top10_concentration_pct: Optional[float],
) -> List[FundDimensionScore]:
    if completeness < MIN_COMPLETENESS_FOR_DIMENSIONS:
        return []

    scores: List[FundDimensionScore] = []

    cost_score = score_cost_dimension(expense_ratio)
    if cost_score is not None:
        scores.append(cost_score)

    liquidity_score = score_liquidity_dimension(aum, volume, avg_volume)
    if liquidity_score is not None:
        scores.append(liquidity_score)

    concentration_score = score_concentration_dimension(top10_concentration_pct)
    if concentration_score is not None:
        scores.append(concentration_score)

    scores.append(
        FundDimensionScore(
            dimension=DIMENSION_DATA_QUALITY,
            score=round(completeness, 1),
            observation=f"ETF veri tamlığı %{completeness:.0f}.",
        )
    )
    return scores


def score_cost_dimension(expense_ratio: Optional[float]) -> Optional[FundDimensionScore]:
    if expense_ratio is None:
        return None
    if expense_ratio <= 0.10:
        score = 95.0
        observation = f"Gider oranı düşük (%{expense_ratio:.2f})."
    elif expense_ratio <= 0.30:
        score = 80.0
        observation = f"Gider oranı makul (%{expense_ratio:.2f})."
    elif expense_ratio <= EXPENSE_HIGH_THRESHOLD_PCT:
        score = 60.0
        observation = f"Gider oranı orta-yüksek (%{expense_ratio:.2f})."
    else:
        score = 30.0
        observation = f"Gider oranı yüksek (%{expense_ratio:.2f})."
    return FundDimensionScore(
        dimension=DIMENSION_COST,
        score=score,
        observation=observation,
    )


def score_liquidity_dimension(
    aum: Optional[float],
    volume: Optional[float],
    avg_volume: Optional[float],
) -> Optional[FundDimensionScore]:
    aum_score = _tier_score(aum, AUM_LIQUIDITY_TIERS)
    volume_score = _tier_score(volume or avg_volume, VOLUME_LIQUIDITY_TIERS)
    if aum_score is None and volume_score is None:
        return None
    if aum_score is not None and volume_score is not None:
        score = round((aum_score + volume_score) / 2, 1)
        observation = "AUM ve işlem hacmi birlikte değerlendirildi."
    elif aum_score is not None:
        score = aum_score
        observation = "Likidite AUM verisine göre değerlendirildi."
    else:
        score = volume_score or 0.0
        observation = "Likidite işlem hacmine göre değerlendirildi."
    return FundDimensionScore(
        dimension=DIMENSION_LIQUIDITY,
        score=score,
        observation=observation,
    )


def score_concentration_dimension(
    top10_concentration_pct: Optional[float],
) -> Optional[FundDimensionScore]:
    if top10_concentration_pct is None:
        return None
    if top10_concentration_pct <= 25:
        score = 90.0
        observation = f"Top-10 yoğunluk düşük (%{top10_concentration_pct:.1f})."
    elif top10_concentration_pct <= TOP10_CONCENTRATION_RISK_THRESHOLD_PCT:
        score = 65.0
        observation = f"Top-10 yoğunluk orta (%{top10_concentration_pct:.1f})."
    else:
        score = 35.0
        observation = f"Top-10 yoğunluk yüksek (%{top10_concentration_pct:.1f})."
    return FundDimensionScore(
        dimension=DIMENSION_CONCENTRATION,
        score=score,
        observation=observation,
    )


def _tier_score(value: Optional[float], tiers: Tuple[Tuple[float, float], ...]) -> Optional[float]:
    if value is None:
        return None
    for threshold, score in tiers:
        if value >= threshold:
            return score
    return 25.0


def _build_labels(
    *,
    completeness: float,
    expense_ratio: Optional[float],
    top10_concentration_pct: Optional[float],
    participation_source: Optional[str],
) -> List[str]:
    labels: List[str] = []
    if completeness < MIN_COMPLETENESS_VERI_YETERSIZ:
        labels.append(LABEL_VERI_YETERSIZ)
    elif completeness >= MIN_COMPLETENESS_INCELEME:
        labels.append(LABEL_INCELEME_UYGUN)

    if expense_ratio is not None and expense_ratio > EXPENSE_HIGH_THRESHOLD_PCT:
        labels.append(LABEL_YUKSEK_MALIYET)

    if (
        top10_concentration_pct is not None
        and top10_concentration_pct > TOP10_CONCENTRATION_RISK_THRESHOLD_PCT
    ):
        labels.append(LABEL_YOGUNLASMA_RISKI)

    if participation_source == PARTICIPATION_SOURCE_CONFIGURED:
        labels.append(LABEL_CONFIGURED_PARTICIPATION)

    return labels
