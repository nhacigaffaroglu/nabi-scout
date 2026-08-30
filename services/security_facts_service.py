"""Canonical SecurityFacts builder.

Single entry for gathering existing canonical data into the 8A/8B contract.
Consumers must not construct SecurityFacts independently.

Source precedence (audit-first, production ownership):

Identity:
  Security Master (including bist_listing for BIST pilots) → candidate listing fields → unavailable
  BIST identity/currency does not invent financial or valuation completeness.

Financial statement facts:
  SEC extract_financials (passed in or local cache replay) for US
  → official normalized KAP facts for BIST pilots only (never US)
  → scanner-persisted candidate financials (themselves SEC-derived)
  → Participation financial_inputs (revenue/assets/debt/cash only)
  → Company Intelligence already-loaded trends (fallback, marked)
  → unavailable

Market / valuation levels:
  official Borsa Istanbul THB close when provided (BIST only; no invented market cap)
  → persisted candidate price/mcap/multiples
  → Company Intelligence already-loaded snapshot/valuation
  → derived from comparable SEC + price facts
  → unavailable

Participation:
  canonical snapshot / queue only (not built here)

Momentum:
  local wealth_portfolio_snapshots marks (if sufficient distinct observations)
  → persisted candidate returns
  → unavailable (FMP historical-price-eod/light is plan-restricted)

No live FMP calls. No SEC network unless a caller already extracted
financials or local SecCompanyFactsCache can replay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Mapping, Optional

from services.bist_symbol_mapping import normalize_bist_symbol
from services.security_intelligence_contract import (
    AUTHORITY_BORSA_ISTANBUL,
    AUTHORITY_CANDIDATE,
    AUTHORITY_COMPANY_INTELLIGENCE,
    AUTHORITY_DERIVED,
    AUTHORITY_KAP,
    AUTHORITY_MIXED,
    AUTHORITY_PARTICIPATION,
    AUTHORITY_SEC,
    AUTHORITY_SECURITY_MASTER,
    AUTHORITY_UNKNOWN,
    CRITICAL_FACT_FIELDS,
    FACTS_VERSION,
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    FactProvenance,
    PERCENT_FACT_FIELDS,
    PERIOD_FY,
    PERIOD_INCOMPATIBLE,
    PERIOD_MIXED,
    PERIOD_Q,
    PERIOD_TTM,
    PERIOD_UNKNOWN,
    PERIOD_YTD,
    SecurityFacts,
)


NUMERIC_FACT_FIELDS = tuple(
    item.name
    for item in fields(SecurityFacts)
    if item.name
    not in {
        "symbol",
        "name",
        "instrument_type",
        "economic_layer",
        "exchange",
        "currency",
        "source",
        "as_of",
        "stale",
        "missing_fields",
        "provenance",
        "completeness_pct",
        "freshness_status",
        "authority_status",
        "period_compatibility",
        "period_kind",
        "missing_critical_fields",
        "facts_version",
    }
)

KAP_FIELD_MAP = {
    "revenue": "revenue",
    "operating_income": "operating_income",
    "net_income": "net_income",
    "total_assets": "total_assets",
    "equity": "equity",
    "cash": "cash",
    "total_debt": "total_debt",
    "roa": "roa",
    "roe": "roe",
    "debt_to_equity": "debt_to_equity",
    "current_ratio": "current_ratio",
    "revenue_growth_yoy": "revenue_growth_yoy",
    "revenue_cagr_3y": "revenue_cagr_3y",
    "eps": "eps",
}

SEC_FIELD_MAP = {
    "revenue": "revenue",
    "operating_income": "operating_income",
    "net_income": "net_income",
    "eps": "eps",
    "free_cash_flow": "free_cash_flow",
    "total_assets": "total_assets",
    "total_debt": "total_debt",
    "cash": "cash",
    "equity": "equity",
    "gross_margin": "gross_margin",
    "operating_margin": "operating_margin",
    "net_margin": "net_margin",
    "fcf_margin": "free_cash_flow_margin",
    "roe": "roe",
    "roa": "roa",
    "roic": "roic",
    "revenue_growth_yoy": "revenue_growth_1y",
    "revenue_cagr_3y": "revenue_cagr_3y",
    "eps_growth_yoy": "eps_growth_1y",
    "eps_cagr_3y": "eps_cagr_3y",
    "fcf_cagr_3y": "fcf_cagr_3y",
    "debt_to_equity": "debt_to_equity",
    "net_debt": "net_debt",
    "net_debt_to_fcf": "net_debt_to_fcf",
    "current_ratio": "current_ratio",
    "interest_coverage": "interest_coverage",
    "share_change_3y": "share_change_3y",
    "payout_ratio": "payout_ratio",
}

CANDIDATE_FIELD_MAP = {
    "price": ("current_price", "price"),
    "market_cap": ("market_cap",),
    "high_52w": ("high_52w", "year_high", "yearHigh"),
    "low_52w": ("low_52w", "year_low", "yearLow"),
    "revenue": ("revenue",),
    "operating_income": ("operating_income",),
    "net_income": ("net_income",),
    "eps": ("eps",),
    "free_cash_flow": ("free_cash_flow",),
    "total_assets": ("total_assets",),
    "total_debt": ("total_debt",),
    "cash": ("cash",),
    "equity": ("equity",),
    "gross_margin": ("gross_margin",),
    "operating_margin": ("operating_margin",),
    "net_margin": ("net_margin",),
    "fcf_margin": ("free_cash_flow_margin", "fcf_margin"),
    "roe": ("roe",),
    "roa": ("roa",),
    "roic": ("roic",),
    "revenue_growth_yoy": ("revenue_growth", "revenue_growth_1y"),
    "revenue_cagr_3y": ("revenue_cagr_3y",),
    "eps_growth_yoy": ("eps_growth", "eps_growth_1y"),
    "eps_cagr_3y": ("eps_cagr_3y",),
    "fcf_growth_yoy": ("fcf_growth", "fcf_growth_1y"),
    "fcf_cagr_3y": ("fcf_cagr_3y",),
    "pe": ("pe_ratio", "pe"),
    "forward_pe": ("forward_pe",),
    "price_to_sales": ("price_to_sales",),
    "price_to_book": ("price_to_book",),
    "ev_ebitda": ("ev_ebitda",),
    "fcf_yield": ("fcf_yield",),
    "debt_to_equity": ("debt_to_equity",),
    "net_debt": ("net_debt",),
    "net_debt_to_fcf": ("net_debt_to_fcf",),
    "current_ratio": ("current_ratio",),
    "interest_coverage": ("interest_coverage",),
    "share_change_3y": ("share_change_3y",),
    "payout_ratio": ("payout_ratio",),
    "average_volume": ("average_volume",),
    "return_1d": ("return_1d",),
    "return_1w": ("return_1w",),
    "return_1m": ("return_1m",),
    "return_3m": ("return_3m",),
    "return_6m": ("return_6m",),
    "return_1y": ("return_12m", "return_1y"),
    "drawdown": ("drawdown",),
    "volatility": ("volatility",),
}

UNIT_FOR_FIELD = {
    **{name: "percent" for name in PERCENT_FACT_FIELDS},
    "price": "price",
    "market_cap": "currency",
    "high_52w": "price",
    "low_52w": "price",
    "revenue": "currency",
    "operating_income": "currency",
    "net_income": "currency",
    "eps": "per_share",
    "free_cash_flow": "currency",
    "total_assets": "currency",
    "total_debt": "currency",
    "cash": "currency",
    "equity": "currency",
    "net_debt": "currency",
    "pe": "ratio",
    "forward_pe": "ratio",
    "price_to_sales": "ratio",
    "price_to_book": "ratio",
    "ev_ebitda": "ratio",
    "debt_to_equity": "ratio",
    "net_debt_to_fcf": "ratio",
    "current_ratio": "ratio",
    "interest_coverage": "ratio",
    "average_volume": "shares",
}


def finite_number(raw: Any) -> Optional[float]:
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def _as_of(*values: Any) -> Optional[str]:
    for raw in values:
        text = _text(raw)
        if text:
            return text
    return None


@dataclass(frozen=True)
class SecurityFactsBuildResult:
    facts: SecurityFacts
    provider_calls: int = 0
    sources_used: tuple[str, ...] = ()
    cache_replayed: bool = False


class _FactSlots:
    def __init__(self) -> None:
        self.values: dict[str, Optional[float]] = {name: None for name in NUMERIC_FACT_FIELDS}
        self.provenance: dict[str, FactProvenance] = {}
        self.sources: list[str] = []

    def set(
        self,
        field: str,
        raw: Any,
        *,
        source: str,
        authority: str,
        source_as_of: Optional[str] = None,
        retrieved_at: Optional[str] = None,
        currency: str = "",
        period_kind: str = PERIOD_UNKNOWN,
        normalization: str = "",
        stale: bool = False,
        confidence: str = "HIGH",
        convert_ratio_percent: bool = False,
    ) -> bool:
        if field not in self.values or self.values[field] is not None:
            return False
        value = finite_number(raw)
        if value is None:
            return False
        applied = normalization
        if convert_ratio_percent and field in PERCENT_FACT_FIELDS and abs(value) <= 1.5:
            value = value * 100.0
            applied = "RATIO_TO_PERCENT"
        self.values[field] = value
        self.provenance[field] = FactProvenance(
            field=field,
            value=value,
            source=source,
            source_as_of=source_as_of,
            retrieved_at=retrieved_at,
            unit=UNIT_FOR_FIELD.get(field, ""),
            currency=currency,
            period_kind=period_kind,
            normalization=applied,
            stale=stale,
            confidence=confidence,
            authority=authority,
        )
        if source not in self.sources:
            self.sources.append(source)
        return True


def _mapping(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    to_dict = getattr(raw, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return dict(payload) if isinstance(payload, Mapping) else {}
    return {}


def _financial_inputs(snapshot: Mapping[str, Any], result: Any) -> dict[str, Any]:
    if result is not None:
        inputs = getattr(result, "financial_inputs", None)
        mapped = _mapping(inputs)
        if mapped:
            return mapped
        payload = _mapping(result)
        nested = payload.get("financial_inputs")
        if isinstance(nested, Mapping):
            return dict(nested)
    payload = snapshot.get("assessment_payload")
    if isinstance(payload, Mapping):
        nested = payload.get("financial_inputs")
        if isinstance(nested, Mapping):
            return dict(nested)
    nested = snapshot.get("financial_inputs")
    if isinstance(nested, Mapping):
        return dict(nested)
    return {}


def _sec_financials(explicit: Optional[Mapping[str, Any]], result: Any) -> dict[str, Any]:
    if explicit:
        return dict(explicit)
    if result is None:
        return {}
    payload = getattr(result, "sec_financials", None)
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def _replay_sec_cache(symbol: str) -> tuple[dict[str, Any], bool]:
    try:
        from repositories.sec_company_facts_cache import SecCompanyFactsCache
    except Exception:
        return {}, False
    try:
        cache = SecCompanyFactsCache()
        evidence = cache.get_latest(symbol=symbol)
        if evidence is None:
            return {}, False
        extracted = cache.replay(evidence)
        return dict(extracted or {}), True
    except Exception:
        return {}, False


def _kap_facts_payload(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if hasattr(raw, "mapped") and hasattr(raw, "symbol"):
        from services.kap_financial_bridge import kap_security_facts_payload

        return kap_security_facts_payload(raw)
    return _mapping(raw)


_BIST_UNOFFICIAL_MARKET_FIELDS = frozenset(
    {
        "price",
        "market_cap",
        "pe",
        "forward_pe",
        "price_to_sales",
        "price_to_book",
        "fcf_yield",
        "ev_ebitda",
    }
)


def _ingest_borsa_market(slots: _FactSlots, payload: Any, *, symbol: str) -> None:
    if payload is None:
        return
    if not normalize_bist_symbol(symbol):
        return
    if hasattr(payload, "symbol"):
        facts_symbol = _text(getattr(payload, "symbol", ""))
        price = getattr(payload, "price", None)
        market_cap = getattr(payload, "market_cap", None)
        currency = _text(getattr(payload, "currency", ""))
        market_date = getattr(payload, "market_date", None)
        source = _text(getattr(payload, "source_dataset", "")) or "borsa_istanbul_thb"
        source_url = _text(getattr(payload, "source_url", ""))
        mcap_class = _text(getattr(payload, "market_cap_classification", ""))
        stale = bool(getattr(payload, "stale", False))
        official_field = _text(getattr(payload, "official_field", ""))
    else:
        mapped = _mapping(payload)
        facts_symbol = _text(mapped.get("symbol"))
        price = mapped.get("price")
        market_cap = mapped.get("market_cap")
        currency = _text(mapped.get("currency"))
        market_date = mapped.get("market_date")
        source = _text(mapped.get("source_dataset") or mapped.get("source")) or "borsa_istanbul_thb"
        source_url = _text(mapped.get("source_url"))
        mcap_class = _text(mapped.get("market_cap_classification"))
        stale = bool(mapped.get("stale"))
        official_field = _text(mapped.get("official_field"))
    if normalize_bist_symbol(facts_symbol) != normalize_bist_symbol(symbol):
        return
    as_of = _as_of(market_date.isoformat() if hasattr(market_date, "isoformat") else market_date)
    del source_url
    slots.set(
        "price",
        price,
        source=source,
        authority=AUTHORITY_BORSA_ISTANBUL,
        source_as_of=as_of,
        currency=currency,
        period_kind=PERIOD_UNKNOWN,
        normalization=official_field or "BORSA_THB_CLOSING_PRICE",
        stale=stale,
        confidence="HIGH",
    )
    allowed_mcap = {
        "DIRECT_OFFICIAL",
        "DERIVED_FROM_OFFICIAL_COMPONENTS",
    }
    if mcap_class in allowed_mcap:
        slots.set(
            "market_cap",
            market_cap,
            source=source,
            authority=AUTHORITY_BORSA_ISTANBUL,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_UNKNOWN,
            normalization=mcap_class,
            stale=stale,
            confidence="HIGH",
        )


def _ingest_kap(slots: _FactSlots, payload: Mapping[str, Any]) -> None:
    if not payload:
        return
    currency = _text(payload.get("financial_currency") or payload.get("currency"))
    as_of = _as_of(payload.get("financial_period_end"), payload.get("as_of"))
    period = _text(payload.get("period_kind")).upper() or PERIOD_FY
    if period in {PERIOD_YTD, PERIOD_TTM, PERIOD_Q}:
        return
    for dest, src in KAP_FIELD_MAP.items():
        slots.set(
            dest,
            payload.get(src),
            source="kap_normalized",
            authority=AUTHORITY_KAP,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_FY,
            normalization=(
                _text(payload.get("eps_normalization"))
                if dest == "eps"
                else _text(payload.get("normalization"))
            )
            or "KAP_FY_BASE_UNITS",
            confidence="HIGH",
        )


def _ingest_sec(slots: _FactSlots, payload: Mapping[str, Any], *, source: str) -> None:
    if not payload:
        return
    currency = _text(payload.get("financial_currency") or payload.get("currency"))
    as_of = _as_of(payload.get("financial_period_end"), payload.get("balance_sheet_period_end"))
    for dest, src in SEC_FIELD_MAP.items():
        slots.set(
            dest,
            payload.get(src),
            source=source,
            authority=AUTHORITY_SEC,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_FY,
            confidence="HIGH",
        )
    prior_fcf = finite_number(payload.get("free_cash_flow_prior"))
    latest_fcf = finite_number(payload.get("free_cash_flow"))
    if prior_fcf not in (None, 0) and latest_fcf is not None:
        slots.set(
            "fcf_growth_yoy",
            (latest_fcf - prior_fcf) / abs(prior_fcf) * 100.0,
            source=source,
            authority=AUTHORITY_DERIVED,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_FY,
            normalization="YOY_FROM_PRIOR_FY",
            confidence="MEDIUM",
        )


def _ingest_candidate(
    slots: _FactSlots,
    row: Mapping[str, Any],
    *,
    stale: bool,
    skip_market_fields: bool = False,
) -> None:
    if not row:
        return
    currency = _text(row.get("financial_currency") or row.get("currency"))
    as_of = _as_of(row.get("financial_period_end"), row.get("source_updated_at"))
    for dest, keys in CANDIDATE_FIELD_MAP.items():
        if skip_market_fields and dest in _BIST_UNOFFICIAL_MARKET_FIELDS:
            continue
        raw = None
        for key in keys:
            raw = row.get(key)
            if raw not in (None, ""):
                break
        period = PERIOD_FY
        if dest.startswith("return_") or dest in {"high_52w", "low_52w", "price", "drawdown", "volatility"}:
            period = PERIOD_UNKNOWN
        if dest in {"pe", "forward_pe", "price_to_sales", "price_to_book", "fcf_yield", "ev_ebitda"}:
            period = PERIOD_MIXED
        slots.set(
            dest,
            raw,
            source="investment_candidates",
            authority=AUTHORITY_CANDIDATE,
            source_as_of=as_of,
            currency=currency,
            period_kind=period,
            stale=stale,
            confidence="HIGH" if dest not in {"pe", "price_to_sales", "price_to_book"} else "MEDIUM",
        )


def _ingest_participation_inputs(
    slots: _FactSlots,
    inputs: Mapping[str, Any],
    *,
    skip_market_fields: bool = False,
) -> None:
    if not inputs:
        return
    as_of = _as_of(inputs.get("as_of_date"))
    currency = _text(inputs.get("currency"))
    mapping = {
        "revenue": "total_revenue",
        "total_assets": "total_assets",
        "total_debt": "total_debt",
        "cash": "cash",
        "market_cap": "market_capitalization",
    }
    for dest, src in mapping.items():
        if skip_market_fields and dest in _BIST_UNOFFICIAL_MARKET_FIELDS:
            continue
        slots.set(
            dest,
            inputs.get(src),
            source="participation_financial_inputs",
            authority=AUTHORITY_PARTICIPATION,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_FY,
            confidence="MEDIUM",
        )


def _ingest_company_intelligence(
    slots: _FactSlots,
    view: Any,
    *,
    skip_market_fields: bool = False,
) -> None:
    if view is None:
        return
    snapshot = getattr(view, "business_snapshot", None)
    if snapshot is not None and not skip_market_fields:
        currency = _text(getattr(snapshot, "currency", "") or getattr(snapshot, "reporting_currency", ""))
        slots.set(
            "market_cap",
            getattr(snapshot, "market_cap", None),
            source="company_intelligence",
            authority=AUTHORITY_COMPANY_INTELLIGENCE,
            currency=currency,
            period_kind=PERIOD_UNKNOWN,
            confidence="MEDIUM",
        )
    trends = getattr(view, "financial_trends", None)
    trend_map = {
        "revenue": "revenue",
        "eps": "eps",
        "operating_margin": "operating_margin",
        "net_margin": "net_margin",
        "free_cash_flow": "free_cash_flow",
        "total_debt": "total_debt",
    }
    if trends is not None:
        for point in getattr(trends, "trends", ()) or ():
            dest = trend_map.get(getattr(point, "metric", ""))
            if dest is None:
                continue
            slots.set(
                dest,
                getattr(point, "latest_value", None),
                source="company_intelligence",
                authority=AUTHORITY_COMPANY_INTELLIGENCE,
                source_as_of=_text(getattr(point, "period", None)) or None,
                period_kind=PERIOD_TTM,
                convert_ratio_percent=True,
                confidence="LOW",
            )
    valuation = getattr(view, "valuation", None)
    value_map = {
        "pe": "pe",
        "forward_pe": "forward_pe",
        "price_to_sales": "ps",
        "price_to_book": "pb",
        "ev_ebitda": "ev_ebitda",
        "fcf_yield": "fcf_yield",
    }
    if valuation is not None and not skip_market_fields:
        for metric in getattr(valuation, "metrics", ()) or ():
            dest = None
            code = _text(getattr(metric, "code", "")).lower()
            for field, alias in value_map.items():
                if code in {field, alias, field.replace("_", "")}:
                    dest = field
                    break
            if dest is None:
                continue
            slots.set(
                dest,
                getattr(metric, "current_value", None),
                source="company_intelligence",
                authority=AUTHORITY_COMPANY_INTELLIGENCE,
                source_as_of=_text(getattr(metric, "fundamental_period_end", None)) or None,
                period_kind=PERIOD_TTM,
                convert_ratio_percent=dest == "fcf_yield",
                confidence="LOW",
            )


def _ingest_local_momentum(
    slots: _FactSlots,
    momentum: Any,
    *,
    client: Any,
    symbol: str,
) -> None:
    payload = momentum
    if payload is None and client is not None:
        try:
            from services.local_market_history_service import LocalMarketHistoryService

            payload = LocalMarketHistoryService(client).compute(symbol)
        except Exception:
            return
    if payload is None:
        return
    values = getattr(payload, "values", None)
    if not isinstance(values, Mapping):
        return
    as_of = None
    if getattr(payload, "provenance", None):
        as_of = payload.provenance[0].source_as_of
    for field, raw in values.items():
        slots.set(
            field,
            raw,
            source="wealth_portfolio_snapshots",
            authority=AUTHORITY_CANDIDATE,
            source_as_of=as_of,
            period_kind=PERIOD_UNKNOWN,
            normalization="LOCAL_MARK_RETURN",
            confidence="MEDIUM",
        )


def _derive_comparable(slots: _FactSlots, currency: str, as_of: Optional[str]) -> None:
    values = slots.values
    period = PERIOD_FY

    def derive(field: str, raw: Optional[float], *, normalization: str) -> None:
        slots.set(
            field,
            raw,
            source="derived",
            authority=AUTHORITY_DERIVED,
            source_as_of=as_of,
            currency=currency,
            period_kind=period,
            normalization=normalization,
            confidence="MEDIUM",
        )

    debt = values.get("total_debt")
    cash = values.get("cash")
    if values.get("net_debt") is None and debt is not None and cash is not None:
        derive("net_debt", debt - cash, normalization="DEBT_MINUS_CASH")

    net_debt = values.get("net_debt")
    fcf = values.get("free_cash_flow")
    if values.get("net_debt_to_fcf") is None and net_debt is not None and fcf not in (None, 0):
        derive("net_debt_to_fcf", net_debt / fcf, normalization="NET_DEBT_OVER_FCF")

    equity = values.get("equity")
    if values.get("debt_to_equity") is None and debt is not None and equity not in (None, 0):
        derive("debt_to_equity", debt / equity, normalization="DEBT_OVER_EQUITY")

    revenue = values.get("revenue")
    operating = values.get("operating_income")
    net_income = values.get("net_income")
    if values.get("operating_margin") is None and operating is not None and revenue not in (None, 0):
        derive("operating_margin", operating / revenue * 100.0, normalization="INCOME_OVER_REVENUE")
    if values.get("net_margin") is None and net_income is not None and revenue not in (None, 0):
        derive("net_margin", net_income / revenue * 100.0, normalization="INCOME_OVER_REVENUE")
    if values.get("fcf_margin") is None and fcf is not None and revenue not in (None, 0):
        derive("fcf_margin", fcf / revenue * 100.0, normalization="FCF_OVER_REVENUE")

    price = values.get("price")
    eps = values.get("eps")
    market_cap = values.get("market_cap")
    if values.get("pe") is None and price is not None and eps not in (None, 0):
        slots.set(
            "pe",
            price / eps,
            source="derived",
            authority=AUTHORITY_DERIVED,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_MIXED,
            normalization="PRICE_OVER_FY_EPS",
            confidence="MEDIUM",
        )
    if values.get("price_to_sales") is None and market_cap is not None and revenue not in (None, 0):
        slots.set(
            "price_to_sales",
            market_cap / revenue,
            source="derived",
            authority=AUTHORITY_DERIVED,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_MIXED,
            normalization="MCAP_OVER_FY_REVENUE",
            confidence="MEDIUM",
        )
    if values.get("price_to_book") is None and market_cap is not None and equity not in (None, 0):
        slots.set(
            "price_to_book",
            market_cap / equity,
            source="derived",
            authority=AUTHORITY_DERIVED,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_MIXED,
            normalization="MCAP_OVER_FY_EQUITY",
            confidence="MEDIUM",
        )
    if values.get("fcf_yield") is None and fcf is not None and market_cap not in (None, 0):
        slots.set(
            "fcf_yield",
            fcf / market_cap * 100.0,
            source="derived",
            authority=AUTHORITY_DERIVED,
            source_as_of=as_of,
            currency=currency,
            period_kind=PERIOD_MIXED,
            normalization="FCF_OVER_MCAP",
            confidence="MEDIUM",
        )


def _quality_summary(slots: _FactSlots, *, stale: bool) -> dict[str, Any]:
    present = [name for name in CRITICAL_FACT_FIELDS if slots.values.get(name) is not None]
    missing = [name for name in CRITICAL_FACT_FIELDS if slots.values.get(name) is None]
    completeness = round(100.0 * len(present) / len(CRITICAL_FACT_FIELDS), 1)
    authorities = {
        item.authority for item in slots.provenance.values() if item.authority != AUTHORITY_DERIVED
    }
    if stale:
        freshness = FRESHNESS_STALE
    elif any(item.stale for item in slots.provenance.values()):
        freshness = FRESHNESS_STALE
    elif slots.provenance:
        freshness = FRESHNESS_FRESH
    else:
        freshness = FRESHNESS_UNKNOWN
    incompatible = (
        {PERIOD_FY, PERIOD_YTD},
        {PERIOD_TTM, PERIOD_YTD},
        {PERIOD_FY, PERIOD_Q},
        {PERIOD_TTM, PERIOD_Q},
        {PERIOD_YTD, PERIOD_Q},
    )
    if AUTHORITY_SEC in authorities and len(authorities) == 1:
        authority = AUTHORITY_SEC
    elif AUTHORITY_SEC in authorities:
        authority = AUTHORITY_MIXED
    elif AUTHORITY_KAP in authorities and len(authorities) == 1:
        authority = AUTHORITY_KAP
    elif AUTHORITY_KAP in authorities:
        authority = AUTHORITY_MIXED
    elif AUTHORITY_BORSA_ISTANBUL in authorities and len(authorities) == 1:
        authority = AUTHORITY_BORSA_ISTANBUL
    elif AUTHORITY_CANDIDATE in authorities and len(authorities) == 1:
        authority = AUTHORITY_CANDIDATE
    elif AUTHORITY_PARTICIPATION in authorities and len(authorities) == 1:
        authority = AUTHORITY_PARTICIPATION
    elif authorities:
        authority = AUTHORITY_MIXED
    else:
        authority = AUTHORITY_UNKNOWN
    periods = {
        item.period_kind
        for item in slots.provenance.values()
        if item.period_kind not in {"", PERIOD_UNKNOWN}
    }
    if PERIOD_INCOMPATIBLE in periods or any(pair <= periods for pair in incompatible):
        compatibility = PERIOD_INCOMPATIBLE
        period_kind = PERIOD_INCOMPATIBLE
    elif PERIOD_MIXED in periods or ({PERIOD_FY, PERIOD_TTM} <= periods):
        compatibility = PERIOD_MIXED
        period_kind = PERIOD_MIXED
    elif PERIOD_FY in periods and len(periods) == 1:
        compatibility = PERIOD_FY
        period_kind = PERIOD_FY
    elif len(periods) == 1:
        compatibility = next(iter(periods))
        period_kind = compatibility
    elif periods:
        compatibility = PERIOD_MIXED
        period_kind = PERIOD_MIXED
    else:
        compatibility = PERIOD_UNKNOWN
        period_kind = PERIOD_UNKNOWN
    return {
        "completeness_pct": completeness,
        "freshness_status": freshness,
        "authority_status": authority,
        "period_compatibility": compatibility,
        "period_kind": period_kind,
        "missing_critical_fields": tuple(missing),
    }


def _winning_identity_fact(resolution: Any) -> Any:
    facts = getattr(resolution, "facts", ()) or ()
    source = getattr(resolution, "source", None)
    for fact in facts:
        if getattr(fact, "source", None) == source:
            return fact
    return facts[0] if facts else None


def _resolve_identity_resolution(symbol: str, security_resolution: Any) -> Any:
    if security_resolution is not None:
        return security_resolution
    if not normalize_bist_symbol(symbol):
        return None
    from services.security_master_service import SecurityMasterService

    return SecurityMasterService().resolve_security(symbol)


class SecurityFactsService:
    """Canonical fact assembler. No writes. No live provider calls by default."""

    def build(
        self,
        symbol: str,
        *,
        candidate: Optional[Mapping[str, Any]] = None,
        participation_snapshot: Optional[Mapping[str, Any]] = None,
        participation_result: Any = None,
        sec_financials: Optional[Mapping[str, Any]] = None,
        kap_financials: Optional[Mapping[str, Any]] = None,
        bist_market_facts: Any = None,
        company_intelligence: Any = None,
        security_resolution: Any = None,
        instrument_type: str = "",
        economic_layer: Optional[str] = None,
        stale: bool = False,
        allow_sec_cache_replay: bool = True,
        client: Any = None,
        local_momentum: Any = None,
    ) -> SecurityFacts:
        return self.build_detailed(
            symbol,
            candidate=candidate,
            participation_snapshot=participation_snapshot,
            participation_result=participation_result,
            sec_financials=sec_financials,
            kap_financials=kap_financials,
            bist_market_facts=bist_market_facts,
            company_intelligence=company_intelligence,
            security_resolution=security_resolution,
            instrument_type=instrument_type,
            economic_layer=economic_layer,
            stale=stale,
            allow_sec_cache_replay=allow_sec_cache_replay,
            client=client,
            local_momentum=local_momentum,
        ).facts

    def build_detailed(
        self,
        symbol: str,
        *,
        candidate: Optional[Mapping[str, Any]] = None,
        participation_snapshot: Optional[Mapping[str, Any]] = None,
        participation_result: Any = None,
        sec_financials: Optional[Mapping[str, Any]] = None,
        kap_financials: Optional[Mapping[str, Any]] = None,
        bist_market_facts: Any = None,
        company_intelligence: Any = None,
        security_resolution: Any = None,
        instrument_type: str = "",
        economic_layer: Optional[str] = None,
        stale: bool = False,
        allow_sec_cache_replay: bool = True,
        client: Any = None,
        local_momentum: Any = None,
    ) -> SecurityFactsBuildResult:
        ticker = normalize_bist_symbol(symbol) or _text(symbol).upper()
        cand = dict(candidate or {})
        snap = dict(participation_snapshot or {})
        slots = _FactSlots()
        cache_replayed = False
        is_bist = bool(normalize_bist_symbol(ticker))

        extracted: dict[str, Any] = {}
        if is_bist:
            _ingest_kap(slots, _kap_facts_payload(kap_financials))
            _ingest_borsa_market(slots, bist_market_facts, symbol=ticker)
        else:
            extracted = _sec_financials(sec_financials, participation_result)
            sec_source = "sec_extract_financials"
            if not extracted and allow_sec_cache_replay:
                extracted, cache_replayed = _replay_sec_cache(ticker)
                if extracted:
                    sec_source = "sec_company_facts_cache"
            _ingest_sec(slots, extracted, source=sec_source)
        official_stale = bool(getattr(bist_market_facts, "stale", False)) if bist_market_facts is not None else False
        candidate_stale = stale or _text(cand.get("freshness_status")).upper() == "STALE" or official_stale
        skip_unofficial_market = is_bist and bist_market_facts is not None
        _ingest_candidate(slots, cand, stale=candidate_stale, skip_market_fields=skip_unofficial_market)
        _ingest_participation_inputs(
            slots,
            _financial_inputs(snap, participation_result),
            skip_market_fields=skip_unofficial_market,
        )
        _ingest_company_intelligence(
            slots,
            company_intelligence,
            skip_market_fields=skip_unofficial_market,
        )
        _ingest_local_momentum(slots, local_momentum, client=client, symbol=ticker)

        kap_payload = _kap_facts_payload(kap_financials) if is_bist else {}
        currency = ""
        if extracted:
            currency = _text(extracted.get("financial_currency") or extracted.get("currency"))
        currency = currency or _text(kap_payload.get("financial_currency") or kap_payload.get("currency"))
        currency = currency or _text(cand.get("financial_currency") or cand.get("currency"))
        market_as_of = None
        if is_bist and bist_market_facts is not None:
            raw_market_date = getattr(bist_market_facts, "market_date", None)
            if hasattr(raw_market_date, "isoformat"):
                market_as_of = raw_market_date.isoformat()
            else:
                market_as_of = _text(raw_market_date) or None
        as_of = _as_of(
            (extracted or {}).get("financial_period_end"),
            kap_payload.get("financial_period_end"),
            cand.get("financial_period_end"),
            cand.get("source_updated_at"),
            snap.get("assessed_at"),
            snap.get("as_of"),
            market_as_of,
        )
        resolution = _resolve_identity_resolution(ticker, security_resolution)
        name = ""
        exchange = ""
        resolved_type = instrument_type
        if resolution is not None:
            resolved_type = resolved_type or _text(getattr(resolution, "instrument_type", ""))
            winning = _winning_identity_fact(resolution)
            if winning is not None:
                name = _text(getattr(winning, "issuer_name", ""))
                exchange = _text(getattr(winning, "exchange", ""))
                metadata = getattr(winning, "metadata", None) or {}
                if isinstance(metadata, Mapping):
                    currency = currency or _text(metadata.get("currency"))
            if hasattr(resolution, "to_dict"):
                slots.sources.append("security_master")
        name = name or _text(cand.get("company_name"))
        exchange = exchange or _text(cand.get("exchange_name") or cand.get("exchange"))
        resolved_type = resolved_type or _text(cand.get("security_type"))
        _derive_comparable(slots, currency, as_of)

        quality = _quality_summary(slots, stale=candidate_stale)
        missing = tuple(name for name, value in slots.values.items() if value is None)
        source_label = "+".join(slots.sources) if slots.sources else "unavailable"
        facts = SecurityFacts(
            symbol=ticker,
            name=name,
            instrument_type=resolved_type,
            economic_layer=economic_layer,
            exchange=exchange,
            currency=currency,
            source=source_label,
            as_of=as_of,
            stale=candidate_stale,
            missing_fields=missing,
            provenance=tuple(slots.provenance[name] for name in NUMERIC_FACT_FIELDS if name in slots.provenance),
            facts_version=FACTS_VERSION,
            **slots.values,
            **quality,
        )
        return SecurityFactsBuildResult(
            facts=facts,
            provider_calls=0,
            sources_used=tuple(slots.sources),
            cache_replayed=cache_replayed,
        )


def facts_from_candidate(
    raw: Optional[Mapping[str, Any]],
    *,
    symbol: str,
    instrument_type: str = "",
    economic_layer: Optional[str] = None,
    stale: bool = False,
) -> SecurityFacts:
    """Backward-compatible candidate-only path. Prefer SecurityFactsService.build."""
    return SecurityFactsService().build(
        symbol,
        candidate=raw,
        instrument_type=instrument_type,
        economic_layer=economic_layer,
        stale=stale,
        allow_sec_cache_replay=False,
    )
