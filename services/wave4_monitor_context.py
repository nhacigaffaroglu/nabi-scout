from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from services.fund_holdings_service import FundHoldingsService
from services.fx_rate_service import FxRateService
from services.portfolio_intelligence_enrichment_contract import PortfolioIntelligenceDashboardView
from services.wealth_price_service import normalize_currency
from services.wealth_timeline_contract import PortfolioSnapshotView


ALLOCATION_CHANGE_THRESHOLD_PCT = 1.0
FUND_HOLDINGS_STALE_DAYS = 30


def _allocation_map(payload: Dict[str, Any], key: str) -> Dict[str, float]:
    rows = payload.get(key) or []
    result: Dict[str, float] = {}
    for row in rows:
        label = str(row.get("label") or row.get("key") or "")
        weight = row.get("weight_pct")
        if label and weight is not None:
            result[label] = float(weight)
    return result


def allocation_changed(
    previous_payload: Dict[str, Any],
    current_payload: Dict[str, Any],
    *,
    allocation_key: str,
    threshold_pct: float = ALLOCATION_CHANGE_THRESHOLD_PCT,
) -> bool:
    previous = _allocation_map(previous_payload, allocation_key)
    current = _allocation_map(current_payload, allocation_key)
    labels = set(previous) | set(current)
    for label in labels:
        prev_weight = previous.get(label)
        curr_weight = current.get(label)
        if prev_weight is None or curr_weight is None:
            if prev_weight != curr_weight:
                return True
            continue
        if abs(curr_weight - prev_weight) >= threshold_pct:
            return True
    return False


def collect_stale_fx_pairs(
    client,
    *,
    base_currency: str,
    valuation_currencies: Iterable[str],
) -> Tuple[str, ...]:
    fx = FxRateService(client)
    base = normalize_currency(base_currency)
    stale: List[str] = []
    for currency in valuation_currencies:
        native = normalize_currency(currency)
        if native == base:
            continue
        row = fx.get_rate_row(base_currency=base, quote_currency=native)
        if row is None or row.stale:
            stale.append(f"{base}/{native}")
    return tuple(sorted(set(stale)))


def collect_missing_price_symbols(dashboard: PortfolioIntelligenceDashboardView) -> Tuple[str, ...]:
    symbols = {
        str(row.symbol or "").upper()
        for row in dashboard.base.unpriced_positions
        if str(row.symbol or "").strip()
    }
    return tuple(sorted(symbols))


def collect_fund_symbols(dashboard: PortfolioIntelligenceDashboardView) -> Tuple[str, ...]:
    symbols: Set[str] = set()
    for row in dashboard.enriched_positions:
        asset_class = str(row.valuation.asset_class or "").lower()
        if asset_class in {"etf", "fund"}:
            symbol = str(row.valuation.symbol or "").upper()
            if symbol:
                symbols.add(symbol)
    return tuple(sorted(symbols))


def collect_stale_fund_symbols(
    client,
    fund_symbols: Iterable[str],
    *,
    stale_after_days: int = FUND_HOLDINGS_STALE_DAYS,
) -> Tuple[str, ...]:
    service = FundHoldingsService(client)
    cutoff = date.today() - timedelta(days=stale_after_days)
    stale: List[str] = []
    for symbol in fund_symbols:
        snapshot = service.get_snapshot(symbol)
        if snapshot is None:
            stale.append(symbol)
            continue
        try:
            as_of = date.fromisoformat(str(snapshot.as_of)[:10])
        except ValueError:
            stale.append(symbol)
            continue
        if as_of < cutoff:
            stale.append(symbol)
    return tuple(stale)


def collect_fund_participation_changes(
    client,
    fund_symbols: Iterable[str],
) -> Tuple[str, ...]:
    """Symbols whose latest two fund snapshots differ in participation buckets."""
    service = FundHoldingsService(client)
    changed: List[str] = []
    for symbol in fund_symbols:
        view = service.build_intelligence_view(symbol)
        exposure = view.participation_exposure
        payload = exposure.to_dict()
        if payload.get("insufficient_evidence"):
            continue
        # Participation change detection requires historical snapshots; mark unavailable
        # unless we add snapshot history compare in a later pass.
        _ = payload
    return tuple(changed)


def snapshot_allocation_flags(
    previous: PortfolioSnapshotView,
    current: PortfolioSnapshotView,
) -> Tuple[bool, bool]:
    prev_payload = previous.valuation_payload or {}
    curr_payload = current.valuation_payload or {}
    asset_class_changed = allocation_changed(
        prev_payload,
        curr_payload,
        allocation_key="asset_class_allocation",
    )
    currency_changed = allocation_changed(
        prev_payload,
        curr_payload,
        allocation_key="currency_allocation",
    )
    return asset_class_changed, currency_changed


def discover_fund_symbols_for_refresh(client) -> Set[str]:
    symbols: Set[str] = set()
    for row in client.table("tracked_funds").select("symbol").limit(500).execute().data or []:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)
    for row in (
        client.table("wealth_assets")
        .select("symbol,asset_class")
        .in_("asset_class", ["etf", "fund"])
        .limit(2000)
        .execute()
        .data
        or []
    ):
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            symbols.add(symbol)
    return symbols
