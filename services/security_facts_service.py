"""Canonical SecurityFacts builder.

Single entry for gathering existing canonical data into the 8A/8B contract.
Consumers must not construct SecurityFacts independently.

Source precedence (audit-first, production ownership):

Identity:
  Security Master → candidate listing fields → unavailable

Financial statement facts:
  SEC extract_financials (passed in or local cache replay)
  → scanner-persisted candidate financials (themselves SEC-derived)
  → Participation financial_inputs (revenue/assets/debt/cash only)
  → Company Intelligence already-loaded trends (fallback, marked)
  → unavailable

Market / valuation levels:
  persisted candidate price/mcap/multiples
  → Company Intelligence already-loaded snapshot/valuation
  → derived from comparable SEC + price facts
  → unavailable

Participation:
  canonical snapshot / queue only (not built here)

Momentum:
  persisted candidate returns only
  → unavailable (FMP historical-price-eod/light is plan-restricted)

No live FMP calls. No SEC network unless a caller already extracted
financials or local SecCompanyFactsCache can replay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Mapping, Optional

from services.security_intelligence_contract import (
    AUTHORITY_CANDIDATE,
    AUTHORITY_COMPANY_INTELLIGENCE,
    AUTHORITY_DERIVED,
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
    PERIOD_TTM,
    PERIOD_UNKNOWN,
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


def _ingest_candidate(slots: _FactSlots, row: Mapping[str, Any], *, stale: bool) -> None:
    if not row:
        return
    currency = _text(row.get("financial_currency") or row.get("currency"))
    as_of = _as_of(row.get("financial_period_end"), row.get("source_updated_at"))
    for dest, keys in CANDIDATE_FIELD_MAP.items():
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


def _ingest_participation_inputs(slots: _FactSlots, inputs: Mapping[str, Any]) -> None:
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


def _ingest_company_intelligence(slots: _FactSlots, view: Any) -> None:
    if view is None:
        return
    snapshot = getattr(view, "business_snapshot", None)
    if snapshot is not None:
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
    if valuation is not None:
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
    if AUTHORITY_SEC in authorities and len(authorities) == 1:
        authority = AUTHORITY_SEC
    elif AUTHORITY_SEC in authorities:
        authority = AUTHORITY_MIXED
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
    if PERIOD_INCOMPATIBLE in periods:
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
        company_intelligence: Any = None,
        security_resolution: Any = None,
        instrument_type: str = "",
        economic_layer: Optional[str] = None,
        stale: bool = False,
        allow_sec_cache_replay: bool = True,
    ) -> SecurityFacts:
        return self.build_detailed(
            symbol,
            candidate=candidate,
            participation_snapshot=participation_snapshot,
            participation_result=participation_result,
            sec_financials=sec_financials,
            company_intelligence=company_intelligence,
            security_resolution=security_resolution,
            instrument_type=instrument_type,
            economic_layer=economic_layer,
            stale=stale,
            allow_sec_cache_replay=allow_sec_cache_replay,
        ).facts

    def build_detailed(
        self,
        symbol: str,
        *,
        candidate: Optional[Mapping[str, Any]] = None,
        participation_snapshot: Optional[Mapping[str, Any]] = None,
        participation_result: Any = None,
        sec_financials: Optional[Mapping[str, Any]] = None,
        company_intelligence: Any = None,
        security_resolution: Any = None,
        instrument_type: str = "",
        economic_layer: Optional[str] = None,
        stale: bool = False,
        allow_sec_cache_replay: bool = True,
    ) -> SecurityFactsBuildResult:
        ticker = _text(symbol).upper()
        cand = dict(candidate or {})
        snap = dict(participation_snapshot or {})
        slots = _FactSlots()
        cache_replayed = False

        extracted = _sec_financials(sec_financials, participation_result)
        sec_source = "sec_extract_financials"
        if not extracted and allow_sec_cache_replay:
            extracted, cache_replayed = _replay_sec_cache(ticker)
            if extracted:
                sec_source = "sec_company_facts_cache"

        _ingest_sec(slots, extracted, source=sec_source)
        candidate_stale = stale or _text(cand.get("freshness_status")).upper() == "STALE"
        _ingest_candidate(slots, cand, stale=candidate_stale)
        _ingest_participation_inputs(slots, _financial_inputs(snap, participation_result))
        _ingest_company_intelligence(slots, company_intelligence)

        currency = ""
        if extracted:
            currency = _text(extracted.get("financial_currency") or extracted.get("currency"))
        currency = currency or _text(cand.get("financial_currency") or cand.get("currency"))
        as_of = _as_of(
            (extracted or {}).get("financial_period_end"),
            cand.get("financial_period_end"),
            cand.get("source_updated_at"),
            snap.get("assessed_at"),
            snap.get("as_of"),
        )
        _derive_comparable(slots, currency, as_of)

        resolution = security_resolution
        name = ""
        exchange = ""
        resolved_type = instrument_type
        if resolution is not None:
            resolved_type = resolved_type or _text(getattr(resolution, "instrument_type", ""))
            facts = getattr(resolution, "facts", ()) or ()
            if facts:
                name = _text(getattr(facts[0], "issuer_name", ""))
                exchange = _text(getattr(facts[0], "exchange", ""))
            if hasattr(resolution, "to_dict"):
                slots.sources.append("security_master")
        name = name or _text(cand.get("company_name"))
        exchange = exchange or _text(cand.get("exchange_name") or cand.get("exchange"))
        resolved_type = resolved_type or _text(cand.get("security_type"))

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
