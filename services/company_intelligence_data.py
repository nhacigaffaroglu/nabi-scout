from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
    peer_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    peer_ratios_ttm: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
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
        return None
    except Exception as exc:
        bundle.failures.append(f"{label}:{exc.__class__.__name__}")
        return None


def load_company_provider_bundle(fmp: FMPClient, symbol: str) -> CompanyProviderBundle:
    normalized = symbol.strip().upper()
    bundle = CompanyProviderBundle(symbol=normalized)

    profile = _safe_fetch("profile", lambda: fmp.profile(normalized), bundle)
    if isinstance(profile, dict):
        bundle.profile = profile

    quote = _safe_fetch("quote", lambda: fmp.quote(normalized), bundle)
    if isinstance(quote, dict):
        bundle.quote = quote

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

    income_a = _safe_fetch("income_annual", lambda: fmp.income_statement(normalized), bundle)
    if isinstance(income_a, list):
        bundle.income_annual = income_a

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

    ratios_history = _safe_fetch("ratios_history", lambda: fmp.ratios(normalized, limit=20), bundle)
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
        bundle.peers = [item for item in peers if item and item != normalized][:8]

    news = _safe_fetch("stock_news", lambda: fmp.stock_news(normalized, limit=30), bundle)
    if isinstance(news, list):
        bundle.news = news

    estimates = _safe_fetch(
        "analyst_estimates",
        lambda: fmp.analyst_estimates(normalized, limit=4),
        bundle,
    )
    if isinstance(estimates, list):
        bundle.analyst_estimates = estimates

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
        bundle.earnings_calendar = calendar

    for peer_symbol in bundle.peers:
        peer_profile = _safe_fetch(
            f"peer_profile:{peer_symbol}",
            lambda peer=peer_symbol: fmp.profile(peer),
            bundle,
        )
        if isinstance(peer_profile, dict):
            bundle.peer_profiles[peer_symbol] = peer_profile
        peer_ratios = _safe_fetch(
            f"peer_ratios_ttm:{peer_symbol}",
            lambda peer=peer_symbol: fmp.ratios_ttm(peer),
            bundle,
        )
        if isinstance(peer_ratios, dict):
            bundle.peer_ratios_ttm[peer_symbol] = peer_ratios

    return bundle


def bundle_call_summary(bundle: CompanyProviderBundle) -> Dict[str, int]:
    return dict(bundle.call_counts)
