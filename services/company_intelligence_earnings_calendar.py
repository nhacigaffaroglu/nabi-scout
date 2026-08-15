from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from services.company_intelligence_constants import PROVIDER_NAME
from services.company_intelligence_contract import CatalystItem


def earnings_row_symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").strip().upper()


def filter_earnings_calendar_for_symbol(
    rows: List[Dict[str, Any]],
    symbol: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Keep only calendar rows explicitly tagged for the requested symbol."""
    normalized = symbol.strip().upper()
    matched: List[Dict[str, Any]] = []
    stats = {
        "total_input": len(rows or []),
        "foreign_symbol_rows": 0,
        "missing_symbol_rows": 0,
    }
    for row in rows or []:
        row_symbol = earnings_row_symbol(row)
        if not row_symbol:
            stats["missing_symbol_rows"] += 1
            continue
        if row_symbol != normalized:
            stats["foreign_symbol_rows"] += 1
            continue
        matched.append(row)
    return matched, stats


def normalize_earnings_event_date(row: Dict[str, Any]) -> Optional[str]:
    raw = row.get("date") or row.get("earningsDate") or row.get("epsDate")
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if len(text) >= 10:
        return text[:10]
    return text or None


def _parse_event_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_upcoming(event_date: str, *, today: Optional[date] = None) -> bool:
    parsed = _parse_event_date(event_date)
    if parsed is None:
        return False
    reference = today or datetime.now(timezone.utc).date()
    return parsed >= reference


def _event_provider_id(row: Dict[str, Any]) -> Optional[str]:
    for key in ("id", "eventId", "uuid"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def build_earnings_catalysts(
    *,
    symbol: str,
    calendar_rows: List[Dict[str, Any]],
    today: Optional[date] = None,
) -> Tuple[CatalystItem, ...]:
    """Build deterministic earnings catalysts from symbol-filtered calendar rows."""
    normalized = symbol.strip().upper()
    if not calendar_rows:
        return ()

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    seen_identity: Set[str] = set()
    for row in calendar_rows:
        event_date = normalize_earnings_event_date(row)
        if not event_date or not _is_upcoming(event_date, today=today):
            continue
        provider_id = _event_provider_id(row)
        identity = provider_id or f"{normalized}:{event_date}"
        if identity in seen_identity:
            continue
        seen_identity.add(identity)
        by_date.setdefault(event_date, []).append(row)

    upcoming_dates = sorted(by_date)
    if not upcoming_dates:
        return ()

    if len(upcoming_dates) == 1:
        event_date = upcoming_dates[0]
        row = by_date[event_date][0]
        provider_id = _event_provider_id(row)
        code = f"earnings-{normalized}-{provider_id or event_date}"
        return (
            CatalystItem(
                code=code,
                catalyst_type="EARNINGS",
                date=event_date,
                description="Planlanan/bilinen kazanç açıklaması tarihi.",
                source=PROVIDER_NAME,
                confidence="HIGH",
                status="UPCOMING",
                related_symbols=(normalized,),
            ),
        )

    return (
        CatalystItem(
            code=f"earnings-{normalized}-conflict",
            catalyst_type="EARNINGS",
            date=upcoming_dates[0],
            description=(
                "Sağlayıcı birden fazla yaklaşan kazanç tarihi döndürdü: "
                + ", ".join(upcoming_dates)
                + ". Tek tarih doğrulanamadı."
            ),
            source=PROVIDER_NAME,
            confidence="LOW",
            status="UNCERTAIN",
            related_symbols=(normalized,),
        ),
    )
