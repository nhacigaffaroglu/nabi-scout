from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from repositories.wealth_portfolio_snapshot_repository import (
    WealthPortfolioSnapshotRepository,
)
from services.candidate_price_service import CandidatePriceService
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.wealth_core_service import WealthCoreService
from services.wealth_performance_engine import snapshot_view_from_row
from services.wealth_snapshot_serializer import (
    snapshot_row_from_intelligence_view,
    unpriced_symbols_from_view,
    valuation_is_complete,
)
from services.wealth_timeline_contract import PortfolioSnapshotView


class SnapshotCaptureStatus(str, Enum):
    CREATED = "CREATED"
    ALREADY_CAPTURED = "ALREADY_CAPTURED"
    NO_PORTFOLIO = "NO_PORTFOLIO"
    VALUATION_UNAVAILABLE = "VALUATION_UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class SnapshotCaptureResult:
    status: SnapshotCaptureStatus
    dry_run: bool
    written: bool
    snapshot_date: Optional[str]
    captured_at: Optional[str]
    snapshot_id: Optional[str]
    priced_market_value: Optional[float]
    valuation_complete: bool
    unpriced_symbols: Tuple[str, ...]
    unpriced_position_count: int
    priced_position_count: int
    total_position_count: int
    base_currency: str
    limitations: Tuple[str, ...]
    error: Optional[str] = None


def _empty_result(
    status: SnapshotCaptureStatus,
    *,
    dry_run: bool,
    error: Optional[str] = None,
) -> SnapshotCaptureResult:
    return SnapshotCaptureResult(
        status=status,
        dry_run=dry_run,
        written=False,
        snapshot_date=None,
        captured_at=None,
        snapshot_id=None,
        priced_market_value=None,
        valuation_complete=False,
        unpriced_symbols=(),
        unpriced_position_count=0,
        priced_position_count=0,
        total_position_count=0,
        base_currency="",
        limitations=(),
        error=error,
    )


def _liabilities_total(wealth: WealthCoreService, portfolio_id: str, base_currency: str) -> float:
    base = str(base_currency or "USD").strip().upper()
    total = 0.0
    for row in wealth.list_liabilities():
        if row.get("portfolio_id") != portfolio_id:
            continue
        if not row.get("is_active", True):
            continue
        if str(row.get("currency") or "").strip().upper() != base:
            continue
        total += float(row.get("principal") or 0.0)
    return total


def _limitations(view) -> Tuple[str, ...]:
    notes: list[str] = []
    if view.unpriced_position_count > 0 or view.foreign_currency_position_count > 0:
        notes.append("PARTIAL_VALUATION")
    if view.mixed_currency_warning:
        notes.append("MIXED_CURRENCY")
    symbols = unpriced_symbols_from_view(view)
    if symbols:
        notes.append("UNPRICED:" + ",".join(symbols))
    return tuple(notes)


def capture_portfolio_snapshot(
    wealth: WealthCoreService,
    portfolio: Optional[Dict[str, Any]],
    *,
    dry_run: bool = False,
    captured_at: Optional[datetime] = None,
    view=None,
    snapshots: Optional[WealthPortfolioSnapshotRepository] = None,
) -> SnapshotCaptureResult:
    """Append-only daily snapshot. Partial valuation is eligible. Never overwrites."""
    repo = snapshots or WealthPortfolioSnapshotRepository(wealth.client)
    if not portfolio or not str(portfolio.get("id") or "").strip():
        return _empty_result(SnapshotCaptureStatus.NO_PORTFOLIO, dry_run=dry_run)

    portfolio_id = str(portfolio.get("id") or "")
    owned = any(
        str(row.get("id") or "") == portfolio_id
        for row in wealth.portfolios.list_for_user(wealth.user_id)
    )
    if not owned:
        return _empty_result(
            SnapshotCaptureStatus.NO_PORTFOLIO,
            dry_run=dry_run,
            error="portfolio_not_owned",
        )

    moment = captured_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    captured_iso = moment.astimezone(timezone.utc).isoformat()
    snapshot_day = repo.istanbul_calendar_date(moment)

    existing = repo.find_for_portfolio_on_date(
        wealth.user_id,
        portfolio_id,
        snapshot_day,
    )
    if existing:
        existing_view = snapshot_view_from_row(existing)
        payload_meta = dict(existing.get("valuation_payload") or {})
        symbols = tuple(
            str(item).strip().upper()
            for item in payload_meta.get("unpriced_symbols") or []
            if str(item).strip()
        )
        return SnapshotCaptureResult(
            status=SnapshotCaptureStatus.ALREADY_CAPTURED,
            dry_run=dry_run,
            written=False,
            snapshot_date=snapshot_day.isoformat(),
            captured_at=str(existing.get("captured_at") or ""),
            snapshot_id=str(existing.get("id") or ""),
            priced_market_value=existing_view.priced_market_value,
            valuation_complete=bool(payload_meta.get("valuation_complete")),
            unpriced_symbols=symbols,
            unpriced_position_count=existing_view.unpriced_position_count,
            priced_position_count=int(
                payload_meta.get("priced_position_count") or 0
            ),
            total_position_count=int(payload_meta.get("total_position_count") or 0),
            base_currency=existing_view.base_currency,
            limitations=("ALREADY_CAPTURED",),
        )

    if view is None:
        try:
            price_service = CandidatePriceService(wealth.client)
            intelligence = PortfolioIntelligenceService(
                wealth,
                price_service,
                nabi_client=None,
            )
            view = intelligence.build_view(portfolio, enrich_nabi=False)
        except Exception as exc:
            return _empty_result(
                SnapshotCaptureStatus.ERROR,
                dry_run=dry_run,
                error=str(exc),
            )

    if view is None:
        return _empty_result(
            SnapshotCaptureStatus.VALUATION_UNAVAILABLE,
            dry_run=dry_run,
            error="valuation_view_missing",
        )

    liabilities_total = _liabilities_total(wealth, portfolio_id, view.base_currency)
    payload = snapshot_row_from_intelligence_view(
        user_id=wealth.user_id,
        portfolio_id=portfolio_id,
        captured_at=captured_iso,
        view=view,
        liabilities_total=liabilities_total,
        snapshot_date=snapshot_day.isoformat(),
    )
    complete = valuation_is_complete(view)
    symbols = unpriced_symbols_from_view(view)
    result_kwargs = dict(
        snapshot_date=snapshot_day.isoformat(),
        captured_at=captured_iso,
        snapshot_id=None,
        priced_market_value=float(view.priced_total_market_value),
        valuation_complete=complete,
        unpriced_symbols=symbols,
        unpriced_position_count=view.unpriced_position_count,
        priced_position_count=view.priced_position_count,
        total_position_count=view.total_position_count,
        base_currency=str(view.base_currency or ""),
        limitations=_limitations(view),
    )

    if dry_run:
        return SnapshotCaptureResult(
            status=SnapshotCaptureStatus.CREATED,
            dry_run=True,
            written=False,
            **result_kwargs,
        )

    try:
        inserted = repo.insert(payload)
    except Exception as exc:
        message = str(exc).lower()
        if "duplicate" in message or "unique" in message:
            return SnapshotCaptureResult(
                status=SnapshotCaptureStatus.ALREADY_CAPTURED,
                dry_run=False,
                written=False,
                **result_kwargs,
            )
        return _empty_result(
            SnapshotCaptureStatus.ERROR,
            dry_run=False,
            error=str(exc),
        )

    return SnapshotCaptureResult(
        status=SnapshotCaptureStatus.CREATED,
        dry_run=False,
        written=True,
        snapshot_date=snapshot_day.isoformat(),
        captured_at=str(inserted.get("captured_at") or captured_iso),
        snapshot_id=str(inserted.get("id") or ""),
        priced_market_value=float(inserted.get("priced_market_value") or view.priced_total_market_value),
        valuation_complete=complete,
        unpriced_symbols=symbols,
        unpriced_position_count=view.unpriced_position_count,
        priced_position_count=view.priced_position_count,
        total_position_count=view.total_position_count,
        base_currency=str(view.base_currency or ""),
        limitations=_limitations(view),
    )
