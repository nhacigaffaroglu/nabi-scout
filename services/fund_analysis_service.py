from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from config.scan_universe import PARTICIPATION_DEFAULTS
from services.fmp_client import FMPClient, FMPError
from services.fund_analysis_contract import (
    ANALYSIS_KIND_FUND,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DIMENSION_CONCENTRATION,
    DIMENSION_COST,
    DIMENSION_DATA_QUALITY,
    DIMENSION_LIQUIDITY,
    LABEL_CONFIGURED_PARTICIPATION,
    LABEL_INCELEME_UYGUN,
    LABEL_VERI_YETERSIZ,
    LABEL_YOGUNLASMA_RISKI,
    LABEL_YUKSEK_MALIYET,
    PARTICIPATION_SOURCE_CONFIGURED,
    FundAnalysisResult,
    FundDimensionScore,
    FundHolding,
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


def analyze_fund(
    resolved: ResolvedSecurity,
    *,
    fmp_client: FMPClient,
) -> FundAnalysisResult:
    symbol = resolved.symbol
    endpoint_status: Dict[str, str] = {}
    warnings: List[str] = []
    unsupported_fields: List[str] = []

    etf_info, endpoint_status["fmp_etf_info"], info_warning = _safe_call(
        fmp_client,
        "etf_info",
        symbol,
        warnings,
    )
    if info_warning:
        warnings.append(info_warning)

    holdings_rows, endpoint_status["fmp_etf_holdings"], holdings_warning = _safe_call_list(
        fmp_client,
        "etf_holdings",
        symbol,
        warnings,
    )
    if holdings_warning:
        warnings.append(holdings_warning)

    profile, endpoint_status["fmp_profile"], profile_warning = _safe_call(
        fmp_client,
        "profile",
        symbol,
        warnings,
    )
    if profile_warning:
        warnings.append(profile_warning)

    quote, endpoint_status["fmp_quote"], quote_warning = _safe_call(
        fmp_client,
        "quote",
        symbol,
        warnings,
    )
    if quote_warning:
        warnings.append(quote_warning)

    fund_name = _first_text(
        etf_info.get("name"),
        etf_info.get("companyName"),
        profile.get("companyName"),
        profile.get("name"),
        quote.get("name"),
        resolved.company_name,
        symbol,
    )
    issuer = _first_text(
        etf_info.get("etfCompany"),
        etf_info.get("issuer"),
        profile.get("companyName"),
    )
    exchange = _first_text(
        etf_info.get("exchange"),
        etf_info.get("exchangeShortName"),
        profile.get("exchange"),
        profile.get("exchangeShortName"),
        resolved.exchange,
    )
    asset_class = _first_text(
        etf_info.get("assetClass"),
        etf_info.get("category"),
        profile.get("sector"),
    )
    domicile = _first_text(
        etf_info.get("domicile"),
        etf_info.get("country"),
        profile.get("country"),
    )
    benchmark = _first_text(
        etf_info.get("indexName"),
        etf_info.get("benchmark"),
        etf_info.get("trackingIndex"),
    )
    inception_date = _first_text(
        etf_info.get("inceptionDate"),
        profile.get("ipoDate"),
    )

    expense_ratio = _normalize_expense_ratio(
        etf_info.get("expenseRatio")
        if etf_info.get("expenseRatio") is not None
        else profile.get("expenseRatio")
    )
    if expense_ratio is None and (
        etf_info.get("expenseRatio") is not None or profile.get("expenseRatio") is not None
    ):
        unsupported_fields.append("expense_ratio")

    distribution_yield = _as_positive_float(
        etf_info.get("distributionYield")
        or etf_info.get("dividendYield")
        or profile.get("lastDiv")
    )

    aum = _as_positive_float(
        etf_info.get("aum")
        or etf_info.get("totalAssets")
        or profile.get("mktCap")
        or profile.get("marketCap")
        or quote.get("marketCap")
    )
    current_price = _as_positive_float(
        quote.get("price")
        or profile.get("price")
        or etf_info.get("price")
    )
    volume = _as_positive_float(quote.get("volume"))
    avg_volume = _as_positive_float(
        quote.get("avgVolume")
        or profile.get("volAvg")
        or etf_info.get("avgVolume")
    )

    parsed_holdings = _parse_holdings(holdings_rows)
    holdings_count = _holdings_count(etf_info, parsed_holdings)
    top_holdings = parsed_holdings[:10]
    top10_concentration_pct = _top10_concentration(top_holdings)

    participation_status, participation_score = participation_for_symbol(symbol)
    participation_source = (
        PARTICIPATION_SOURCE_CONFIGURED
        if symbol in PARTICIPATION_DEFAULTS
        else None
    )

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
        issuer=issuer,
        exchange=exchange,
        asset_class=asset_class,
        domicile=domicile,
        benchmark=benchmark,
        inception_date=inception_date,
        holdings_count=holdings_count,
        top_holdings=top_holdings,
        top10_concentration_pct=top10_concentration_pct,
        expense_ratio=expense_ratio,
        distribution_yield=distribution_yield,
        aum=aum,
        current_price=current_price,
        volume=volume,
        avg_volume=avg_volume,
        participation_status=participation_status,
        participation_score=participation_score,
        participation_source=participation_source,
        data_completeness_pct=completeness,
        analysis_confidence=confidence,
        endpoint_status=endpoint_status,
        warnings=warnings,
        unsupported_fields=unsupported_fields,
        dimension_scores=dimension_scores,
        labels=labels,
    )


def _safe_call(
    fmp_client: FMPClient,
    method_name: str,
    symbol: str,
    warnings: List[str],
) -> Tuple[Dict[str, Any], str, Optional[str]]:
    method = getattr(fmp_client, method_name)
    try:
        payload = method(symbol) or {}
        if not isinstance(payload, dict):
            return {}, "MALFORMED", f"FMP {method_name} beklenmeyen yanıt döndürdü."
        if not payload:
            return {}, "EMPTY", None
        return payload, "OK", None
    except FMPError as exc:
        status = _endpoint_status_from_error(exc)
        warning = _warning_for_error(method_name, exc)
        if warning:
            warnings.append(warning)
        return {}, status, None


def _safe_call_list(
    fmp_client: FMPClient,
    method_name: str,
    symbol: str,
    warnings: List[str],
) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    method = getattr(fmp_client, method_name)
    try:
        payload = method(symbol) or []
        if not isinstance(payload, list):
            return [], "MALFORMED", f"FMP {method_name} beklenmeyen yanıt döndürdü."
        rows = [row for row in payload if isinstance(row, dict)]
        if not rows:
            return [], "EMPTY", None
        return rows, "OK", None
    except FMPError as exc:
        status = _endpoint_status_from_error(exc)
        warning = _warning_for_error(method_name, exc)
        if warning:
            warnings.append(warning)
        return [], status, None


def _endpoint_status_from_error(exc: FMPError) -> str:
    mapping = {
        "rate_limit": "RATE_LIMIT",
        "plan_restricted": "PLAN_RESTRICTED",
        "auth": "AUTH_ERROR",
        "timeout": "TIMEOUT",
        "network": "NETWORK_ERROR",
        "not_found": "NOT_FOUND",
        "transient_http": "SERVER_ERROR",
        "http_error": "SERVER_ERROR",
        "malformed": "MALFORMED",
        "empty": "EMPTY",
    }
    return mapping.get(exc.error_class, "UNAVAILABLE")


def _warning_for_error(method_name: str, exc: FMPError) -> Optional[str]:
    if exc.error_class == "rate_limit":
        return f"FMP {method_name}: rate limit nedeniyle veri alınamadı."
    if exc.error_class == "plan_restricted":
        return f"FMP {method_name}: plan erişimi yok."
    if exc.error_class in {"not_found", "empty"}:
        return None
    return f"FMP {method_name}: {exc}"


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


def _normalize_expense_ratio(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number <= 0.05:
        return round(number * 100, 4)
    return round(number, 4)


def _parse_holdings(rows: List[Dict[str, Any]]) -> List[FundHolding]:
    parsed: List[FundHolding] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        weight = _normalize_weight(
            row.get("weightPercentage")
            or row.get("weight")
            or row.get("percentage")
            or row.get("portfolioWeight")
        )
        if weight is None:
            continue
        parsed.append(
            FundHolding(
                symbol=_first_text(
                    row.get("asset"),
                    row.get("symbol"),
                    row.get("ticker"),
                ),
                name=_first_text(row.get("name"), row.get("companyName")),
                weight_pct=weight,
            )
        )
    parsed.sort(key=lambda item: item.weight_pct or 0.0, reverse=True)
    return parsed


def _normalize_weight(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number <= 1:
        return round(number * 100, 4)
    return round(number, 4)


def _holdings_count(
    etf_info: Dict[str, Any],
    holdings: List[FundHolding],
) -> Optional[int]:
    for key in ("holdingsCount", "numberOfHoldings", "holdings"):
        raw = etf_info.get(key)
        if raw is None:
            continue
        if isinstance(raw, list):
            return len(raw)
        try:
            count = int(raw)
        except (TypeError, ValueError):
            continue
        if count > 0:
            return count
    if holdings:
        return len(holdings)
    return None


def _top10_concentration(holdings: List[FundHolding]) -> Optional[float]:
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
    top_holdings: List[FundHolding],
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
    core_ok = (
        endpoint_status.get("fmp_etf_info") == "OK"
        or endpoint_status.get("fmp_profile") == "OK"
    )
    holdings_ok = endpoint_status.get("fmp_etf_holdings") == "OK"
    if completeness >= 75 and core_ok and holdings_ok:
        return CONFIDENCE_HIGH
    if completeness >= 50 and core_ok:
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
