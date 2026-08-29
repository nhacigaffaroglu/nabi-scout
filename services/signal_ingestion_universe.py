"""Bounded Signal ingestion universe: holdings first, then research candidates.

Participation does not suppress monitoring of an existing US equity holding.
Uygun Değil candidates are not added for discovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from services.bist_symbol_mapping import BIST_PORTFOLIO_SYMBOLS, US_MARKETS
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN_DEGIL
from services.research_workflow_service import normalize_research_status
from services.wealth_asset_classification import (
    CASH_SYMBOL,
    KNOWN_EQUITY_TR,
    KNOWN_ETF_SYMBOLS,
    TF_PARTICIPATION_SYMBOL,
)
from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_FUND,
    normalize_market,
    normalize_symbol,
)


EXCLUDED_ASSET_CLASSES = frozenset(
    {ASSET_CLASS_CASH, ASSET_CLASS_ETF, ASSET_CLASS_FUND, "gold", "sukuk"}
)
EQUITY_KINDS = frozenset({ASSET_CLASS_EQUITY, "common stock", "equity", "hisse", "stock"})
EXCLUDED_SYMBOLS = frozenset(
    {CASH_SYMBOL, TF_PARTICIPATION_SYMBOL, *KNOWN_ETF_SYMBOLS, *KNOWN_EQUITY_TR, *BIST_PORTFOLIO_SYMBOLS}
)
TR_MARKETS = frozenset({"TR", "BIST", "IST", "TURKEY", "TURKIYE", "TÜRKİYE", "XIST"})
TERMINAL_RESEARCH_STATUS = "TAMAMLANDI"
ACTIVE_RESEARCH_STATUSES = frozenset({"INCELEMEDE", "BEKLEMEDE", "TEKRAR_BAK"})


@dataclass(frozen=True)
class SignalUniverseMember:
    symbol: str
    source: str
    cik: Optional[str] = None
    market: str = "US"
    asset_class: str = ASSET_CLASS_EQUITY
    participation_status: Optional[str] = None
    reason: str = ""


@dataclass(frozen=True)
class SignalIngestionUniverse:
    holdings: tuple[str, ...]
    candidates: tuple[str, ...]
    excluded: tuple[tuple[str, str], ...]
    members: tuple[SignalUniverseMember, ...]
    eligible: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ordered_symbols(self) -> tuple[str, ...]:
        return self.eligible or tuple(item.symbol for item in self.members)


def _is_us_equity_market(market: str) -> bool:
    return market in US_MARKETS or market == "US"


def _is_us_equity(
    *,
    symbol: str,
    market: str,
    asset_class: str,
    instrument_type: Optional[str] = None,
) -> bool:
    if symbol in EXCLUDED_SYMBOLS:
        return False
    if market in TR_MARKETS:
        return False
    if not _is_us_equity_market(market):
        return False
    kind = str(instrument_type or asset_class or "").strip().lower()
    if kind in EXCLUDED_ASSET_CLASSES or kind in {"etf", "fund", "cash", "warrant", "right"}:
        return False
    return kind in EQUITY_KINDS


def has_active_research_reason(row: Mapping[str, Any]) -> bool:
    """Category B: canonical in-progress workflow only.

    YENI is the unreviewed default seed. Participation, CIK, decision, and
    research_allowed are not research-workflow activity.
    """
    status = normalize_research_status(row.get("research_status"))
    return status in ACTIVE_RESEARCH_STATUSES


def build_signal_ingestion_universe(
    *,
    holdings: Sequence[Mapping[str, Any]] = (),
    candidates: Sequence[Mapping[str, Any]] = (),
    participation_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
    security_master_by_symbol: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> SignalIngestionUniverse:
    """Holdings first (including Uygun Değil), then open US-equity research candidates."""
    participation = participation_by_symbol or {}
    master = security_master_by_symbol or {}
    excluded: list[tuple[str, str]] = []
    holding_members: list[SignalUniverseMember] = []
    seen: set[str] = set()

    for row in holdings:
        symbol = normalize_symbol(row.get("symbol"))
        if not symbol or symbol in seen:
            continue
        qty = row.get("quantity")
        try:
            quantity = float(qty) if qty is not None else 1.0
        except (TypeError, ValueError):
            quantity = 0.0
        if quantity <= 0:
            excluded.append((symbol, "zero_quantity"))
            continue
        market = normalize_market(row.get("market"))
        asset_class = str(row.get("asset_class") or ASSET_CLASS_EQUITY).strip().lower()
        instrument = str((master.get(symbol) or {}).get("instrument_type") or row.get("instrument_type") or "")
        if not _is_us_equity(symbol=symbol, market=market, asset_class=asset_class, instrument_type=instrument):
            excluded.append((symbol, "not_us_equity_holding"))
            continue
        snap = participation.get(symbol) or {}
        holding_members.append(
            SignalUniverseMember(
                symbol=symbol,
                source="holding",
                cik=str(row.get("cik") or "").strip() or None,
                market=market,
                asset_class=asset_class or ASSET_CLASS_EQUITY,
                participation_status=str(snap.get("status") or row.get("participation_status") or "") or None,
                reason="portfolio_us_equity",
            )
        )
        seen.add(symbol)

    holding_members.sort(key=lambda item: item.symbol)
    candidate_members: list[SignalUniverseMember] = []
    for row in candidates:
        symbol = normalize_symbol(row.get("symbol"))
        if not symbol or symbol in seen:
            continue
        market = normalize_market(row.get("market") or "US")
        asset_class = str(row.get("asset_class") or row.get("asset_type") or ASSET_CLASS_EQUITY).strip().lower()
        instrument = str((master.get(symbol) or {}).get("instrument_type") or row.get("instrument_type") or "")
        if not _is_us_equity(symbol=symbol, market=market, asset_class=asset_class, instrument_type=instrument):
            excluded.append((symbol, "not_us_equity_candidate"))
            continue
        snap = participation.get(symbol) or {}
        status = str(snap.get("status") or row.get("participation_status") or "").strip()
        if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
            excluded.append((symbol, "uygun_degil_not_holding"))
            continue
        workflow = normalize_research_status(row.get("research_status"))
        if workflow == TERMINAL_RESEARCH_STATUS:
            excluded.append((symbol, "research_not_open"))
            continue
        if not has_active_research_reason(row):
            excluded.append((symbol, "not_active_research"))
            continue
        candidate_members.append(
            SignalUniverseMember(
                symbol=symbol,
                source="candidate",
                cik=str(row.get("cik") or "").strip() or None,
                market=market,
                asset_class=asset_class or ASSET_CLASS_EQUITY,
                participation_status=status or None,
                reason="active_us_equity_research",
            )
        )
        seen.add(symbol)

    candidate_members.sort(key=lambda item: item.symbol)
    members = tuple(holding_members + candidate_members)
    return SignalIngestionUniverse(
        holdings=tuple(item.symbol for item in holding_members),
        candidates=tuple(item.symbol for item in candidate_members),
        excluded=tuple(excluded),
        members=members,
        eligible=tuple(item.symbol for item in members),
    )


def apply_symbol_capacity(
    symbols: Sequence[str],
    *,
    max_symbols_per_run: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    cap = max(1, int(max_symbols_per_run))
    ordered = tuple(str(item).strip().upper() for item in symbols if str(item).strip())
    return ordered[:cap], ordered[cap:]
