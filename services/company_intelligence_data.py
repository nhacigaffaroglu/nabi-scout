from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.company_intelligence_constants import MAX_PEER_COUNT
from services.company_intelligence_earnings_calendar import filter_earnings_calendar_for_symbol
from services.company_intelligence_provider_diagnostics import (
    ProviderDiagnostic,
    diagnostic_from_fmp_error,
)
from services.company_intelligence_utils import safe_float
from services.fmp_client import FMPClient, FMPError


@dataclass
class CompanyProviderBundle:
    symbol: str
    profile: Dict[str, Any] = field(default_factory=dict)
    quote: Dict[str, Any] = field(default_factory=dict)
    income_quarterly: List[Dict[str, Any]] = field(default_factory=list)
    balance_quarterly: List[Dict[str, Any]] = field(default_factory=list)
    cashflow_quarterly: List[Dict[str, Any]] = field(default_factory=list)
    income_annual: List[Dict[str, Any]] = field(default_factory=list)
    ratios_ttm: Dict[str, Any] = field(default_factory=dict)
    key_metrics_ttm: Dict[str, Any] = field(default_factory=dict)
    ratios_history: List[Dict[str, Any]] = field(default_factory=list)
    key_metrics_history: List[Dict[str, Any]] = field(default_factory=list)
    peers: List[str] = field(default_factory=list)
    news: List[Dict[str, Any]] = field(default_factory=list)
    analyst_estimates: List[Dict[str, Any]] = field(default_factory=list)
    earnings_surprises: List[Dict[str, Any]] = field(default_factory=list)
    earnings_calendar: List[Dict[str, Any]] = field(default_factory=list)
    sec_financials: Dict[str, Any] = field(default_factory=dict)
    historical_prices: List[Dict[str, Any]] = field(default_factory=list)
    historical_price_scope: Tuple[str, ...] = field(default_factory=tuple)
    market_cap_fallback: Optional[float] = None
    peer_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    peer_ratios_ttm: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    provider_diagnostics: List[ProviderDiagnostic] = field(default_factory=list)
    call_counts: Dict[str, int] = field(default_factory=dict)
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


def _safe_fetch(label: str, callback, bundle: CompanyProviderBundle) -> Any:
    bundle.call_counts[label] = bundle.call_counts.get(label, 0) + 1
    try:
        return callback()
    except FMPError as exc:
        bundle.failures.append(f"{label}:{exc.error_class}")
        bundle.provider_diagnostics.append(diagnostic_from_fmp_error(label, exc))
        return None
    except Exception as exc:
        bundle.failures.append(f"{label}:{exc.__class__.__name__}")
        return None


def load_company_provider_bundle(
    fmp: FMPClient,
    symbol: str,
    *,
    sec_financials: Optional[Dict[str, Any]] = None,
    market_cap_fallback: Optional[float] = None,
) -> CompanyProviderBundle:
    normalized = symbol.strip().upper()
    bundle = CompanyProviderBundle(symbol=normalized)
    if sec_financials:
        bundle.sec_financials = dict(sec_financials)
    if market_cap_fallback is not None:
        fallback = safe_float(market_cap_fallback)
        if fallback is not None and fallback > 0:
            bundle.market_cap_fallback = fallback

    profile = _safe_fetch("profile", lambda: fmp.profile(normalized), bundle)
    if isinstance(profile, dict):
        bundle.profile = profile

    income_q = _safe_fetch(
        "income_quarterly",
        lambda: fmp.income_statement_quarterly(normalized, limit=8),
        bundle,
    )
    if isinstance(income_q, list):
        bundle.income_quarterly = income_q

    balance_q = _safe_fetch(
        "balance_quarterly",
        lambda: fmp.balance_sheet_quarterly(normalized, limit=8),
        bundle,
    )
    if isinstance(balance_q, list):
        bundle.balance_quarterly = balance_q

    cash_q = _safe_fetch(
        "cashflow_quarterly",
        lambda: fmp.cash_flow_quarterly(normalized, limit=8),
        bundle,
    )
    if isinstance(cash_q, list):
        bundle.cashflow_quarterly = cash_q

    ratios_ttm = _safe_fetch("ratios_ttm", lambda: fmp.ratios_ttm(normalized), bundle)
    if isinstance(ratios_ttm, dict):
        bundle.ratios_ttm = ratios_ttm

    key_metrics_ttm = _safe_fetch(
        "key_metrics_ttm",
        lambda: fmp.key_metrics_ttm(normalized),
        bundle,
    )
    if isinstance(key_metrics_ttm, dict):
        bundle.key_metrics_ttm = key_metrics_ttm

    # Keep the company-intelligence hard FMP budget <= 15 calls.
    # When current FMP valuation ratios are unavailable but SEC annual facts exist,
    # FMP valuation-history endpoints cannot produce the active valuation path.
    # Reserve that budget for one bounded fiscal-year historical-price call instead.
    current_valuation_values = (
        safe_float(bundle.ratios_ttm.get("priceToEarningsRatioTTM")),
        safe_float(bundle.ratios_ttm.get("priceToSalesRatioTTM")),
        safe_float(bundle.ratios_ttm.get("priceToBookRatioTTM")),
        safe_float(bundle.ratios_ttm.get("dividendYieldTTM")),
        safe_float(bundle.key_metrics_ttm.get("enterpriseValueOverEBITDATTM")),
        safe_float(bundle.key_metrics_ttm.get("freeCashFlowYieldTTM")),
        safe_float(bundle.key_metrics_ttm.get("earningsYieldTTM")),
    )
    reserve_sec_hybrid_history_slot = bool(bundle.sec_financials) and not any(
        value is not None for value in current_valuation_values
    )
    if not reserve_sec_hybrid_history_slot:
        ratios_history = _safe_fetch(
            "ratios_history",
            lambda: fmp.ratios(normalized, limit=20),
            bundle,
        )
        if isinstance(ratios_history, list):
            bundle.ratios_history = ratios_history

        key_metrics_history = _safe_fetch(
            "key_metrics_history",
            lambda: fmp.key_metrics(normalized, limit=20),
            bundle,
        )
        if isinstance(key_metrics_history, list):
            bundle.key_metrics_history = key_metrics_history

    peers = _safe_fetch("stock_peers", lambda: fmp.stock_peers(normalized), bundle)
    if isinstance(peers, list):
        bundle.peers = [item for item in peers if item and item != normalized][:MAX_PEER_COUNT]

    news = _safe_fetch("stock_news", lambda: fmp.stock_news(normalized, limit=30), bundle)
    if isinstance(news, list):
        bundle.news = news

    surprises = _safe_fetch(
        "earnings_surprises",
        lambda: fmp.earnings_surprises(normalized),
        bundle,
    )
    if isinstance(surprises, list):
        bundle.earnings_surprises = surprises

    calendar = _safe_fetch(
        "earnings_calendar",
        lambda: fmp.earnings_calendar(normalized),
        bundle,
    )
    if isinstance(calendar, list):
        filtered, stats = filter_earnings_calendar_for_symbol(calendar, normalized)
        bundle.earnings_calendar = filtered
        if stats["foreign_symbol_rows"]:
            bundle.failures.append(
                f"earnings_calendar:foreign_symbol_rows:{stats['foreign_symbol_rows']}"
            )

    for peer_symbol in bundle.peers:
        peer_ratios = _safe_fetch(
            f"peer_ratios_ttm:{peer_symbol}",
            lambda peer=peer_symbol: fmp.ratios_ttm(peer),
            bundle,
        )
        if isinstance(peer_ratios, dict):
            bundle.peer_ratios_ttm[peer_symbol] = peer_ratios

    return bundle


def load_sec_hybrid_historical_prices(
    fmp: FMPClient,
    bundle: CompanyProviderBundle,
) -> None:
    from services.company_intelligence_utils import safe_float

    annual_history = bundle.sec_financials.get("annual_history") or []
    period_dates: list[date] = []
    for row in list(annual_history)[:5]:
        shares = safe_float(row.get("weighted_average_shares"))
        revenue = safe_float(row.get("revenue"))
        free_cash_flow = safe_float(row.get("free_cash_flow"))
        if shares is None or shares <= 0:
            continue
        if not ((revenue is not None and revenue > 0) or (free_cash_flow is not None and free_cash_flow > 0)):
            continue
        text = str(row.get("period_end") or "").strip()
        try:
            period_dates.append(date.fromisoformat(text[:10]))
        except (TypeError, ValueError):
            continue
    scope = tuple(sorted(item.isoformat() for item in period_dates))
    if len(scope) < 3:
        return
    if bundle.historical_price_scope == scope and (
        bundle.historical_prices or "historical_price_eod_light" in bundle.call_counts
    ):
        return

    # A changed SEC annual-history scope must never reuse prices from an older scope.
    bundle.historical_prices = []
    bundle.historical_price_scope = scope
    from_date = (min(period_dates) - timedelta(days=7)).isoformat()
    to_date = max(period_dates).isoformat()
    rows = _safe_fetch(
        "historical_price_eod_light",
        lambda: fmp.historical_price_eod_light(
            bundle.symbol,
            from_date=from_date,
            to_date=to_date,
        ),
        bundle,
    )
    if isinstance(rows, list):
        bundle.historical_prices = rows


def max_expected_provider_calls(*, peer_count: int = MAX_PEER_COUNT) -> int:
    """Upper bound for cold company intelligence load."""
    # SEC-hybrid history reserves one slot by skipping two unused FMP valuation-history calls.
    base_calls = 12
    return base_calls + min(peer_count, MAX_PEER_COUNT)


def bundle_call_summary(bundle: CompanyProviderBundle) -> Dict[str, int]:
    return dict(bundle.call_counts)
