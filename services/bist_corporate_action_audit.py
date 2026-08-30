"""Official Borsa/KAP corporate-action evidence for price-series adjustment.

THB daily closes are that day's official unadjusted KAPANIS FIYATI.
Borsa 05.PRO.01 publishes theoretical/reference prices for the next session
limits; it is not a back-adjusted historical series.

US/canonical Momentum is PRICE return. Cash dividends are not added back.
Splits, bonus issues, and rights that change the quote unit require an
official factor or the spanning lookback is CORPORATE_ACTION_UNRESOLVED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from services.bist_thb_history import BistHistoricalPrice
from services.borsa_quotation_basis import SOURCE_THEORETICAL_PRICE


SOURCE_THEORETICAL = SOURCE_THEORETICAL_PRICE
SOURCE_THB_FLAG = "borsa_istanbul_thb_ozsermaye_hali"

STATUS_NONE = "NONE_FOUND_WITHIN_WINDOW"
STATUS_ADJUSTED = "ADJUSTED_OFFICIAL_FACTOR"
STATUS_UNRESOLVED = "CORPORATE_ACTION_UNRESOLVED"
STATUS_RAW_OK = "RAW_UNADJUSTED_NO_PRICE_ADJUSTING_EVENT"

EVENT_BONUS = "BONUS_ISSUE"
EVENT_RIGHTS = "RIGHTS_ISSUE"
EVENT_SPLIT = "STOCK_SPLIT"
EVENT_REVERSE_SPLIT = "REVERSE_SPLIT"
EVENT_CAPITAL_INCREASE = "CAPITAL_INCREASE"
EVENT_CAPITAL_DECREASE = "CAPITAL_DECREASE"
EVENT_CASH_DIVIDEND = "CASH_DIVIDEND"
EVENT_MERGER = "MERGER"
EVENT_DEMERGER = "DEMERGER"
EVENT_THB_FLAG = "THB_CORPORATE_ACTION_FLAG"

PRICE_ADJUSTING = frozenset(
    {
        EVENT_BONUS,
        EVENT_RIGHTS,
        EVENT_SPLIT,
        EVENT_REVERSE_SPLIT,
        EVENT_CAPITAL_INCREASE,
        EVENT_CAPITAL_DECREASE,
        EVENT_MERGER,
        EVENT_DEMERGER,
        EVENT_THB_FLAG,
    }
)


def thb_flag_is_active(flag: object) -> bool:
    text = str(flag or "").strip()
    if not text or text in {"0", "0.0", "FALSE", "false", "NO", "no"}:
        return False
    return True


@dataclass(frozen=True)
class OfficialCorporateAction:
    symbol: str
    event_type: str
    effective_date: date
    official_source: str
    ratio: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    rights_price: Optional[Decimal] = None
    adjustment_required: bool = True
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "event_type": self.event_type,
            "effective_date": self.effective_date.isoformat(),
            "official_source": self.official_source,
            "ratio": str(self.ratio) if self.ratio is not None else None,
            "amount": str(self.amount) if self.amount is not None else None,
            "rights_price": str(self.rights_price) if self.rights_price is not None else None,
            "adjustment_required": self.adjustment_required,
            "notes": list(self.notes),
        }


def official_bonus_or_split_factor(n1: Decimal) -> Optional[Decimal]:
    """05.PRO.01 §7.1 with n2=0, T=0: Ft = Fk / (1+n1). Older prices × 1/(1+n1)."""
    if n1 < 0:
        return None
    try:
        return Decimal("1") / (Decimal("1") + n1)
    except (InvalidOperation, ZeroDivisionError):
        return None


def events_from_thb_flags(
    series: Iterable[BistHistoricalPrice],
) -> tuple[OfficialCorporateAction, ...]:
    found: list[OfficialCorporateAction] = []
    for row in series:
        if not thb_flag_is_active(row.corporate_action_flag):
            continue
        found.append(
            OfficialCorporateAction(
                symbol=row.symbol,
                event_type=EVENT_THB_FLAG,
                effective_date=row.trade_date,
                official_source=SOURCE_THB_FLAG,
                adjustment_required=True,
                notes=("thb_ozsermaye_hali_flag_without_ratio",),
            )
        )
    return tuple(found)


def merge_official_events(
    *groups: Iterable[OfficialCorporateAction],
) -> tuple[OfficialCorporateAction, ...]:
    items = [item for group in groups for item in group]
    typed_dates = {
        (item.symbol, item.effective_date)
        for item in items
        if item.event_type != EVENT_THB_FLAG
    }
    if typed_dates:
        items = [
            item
            for item in items
            if item.event_type != EVENT_THB_FLAG
            or (item.symbol, item.effective_date) not in typed_dates
        ]
    items.sort(key=lambda item: (item.symbol, item.effective_date, item.event_type))
    return tuple(items)


def events_in_window(
    events: Iterable[OfficialCorporateAction],
    *,
    start: date,
    end: date,
) -> tuple[OfficialCorporateAction, ...]:
    return tuple(item for item in events if start <= item.effective_date <= end)


def price_adjusting_events(
    events: Iterable[OfficialCorporateAction],
) -> tuple[OfficialCorporateAction, ...]:
    return tuple(
        item
        for item in events
        if item.adjustment_required and item.event_type in PRICE_ADJUSTING
    )


def official_factor_for_event(event: OfficialCorporateAction) -> Optional[Decimal]:
    if event.event_type == EVENT_CASH_DIVIDEND:
        return Decimal("1")
    if event.event_type in {EVENT_BONUS, EVENT_SPLIT} and event.ratio is not None:
        return official_bonus_or_split_factor(event.ratio)
    if event.event_type == EVENT_REVERSE_SPLIT and event.ratio is not None and event.ratio > 0:
        return event.ratio
    return None


def cumulative_adjustment_factor(
    events: Iterable[OfficialCorporateAction],
    *,
    as_of: date,
) -> Optional[Decimal]:
    """Multiply official factors for price-adjusting events strictly after as_of."""
    factor = Decimal("1")
    for event in events:
        if event.effective_date <= as_of:
            continue
        if event.event_type == EVENT_CASH_DIVIDEND or not event.adjustment_required:
            continue
        piece = official_factor_for_event(event)
        if piece is None:
            return None
        factor *= piece
    return factor


def apply_official_adjustments(
    series: Iterable[BistHistoricalPrice],
    events: Iterable[OfficialCorporateAction],
) -> tuple[tuple[BistHistoricalPrice, ...], str]:
    rows = list(series)
    adjusting = price_adjusting_events(events)
    if not adjusting:
        return tuple(rows), STATUS_RAW_OK
    out: list[BistHistoricalPrice] = []
    for row in rows:
        factor = cumulative_adjustment_factor(adjusting, as_of=row.trade_date)
        if factor is None:
            return tuple(rows), STATUS_UNRESOLVED
        close = float(Decimal(str(row.close)) * factor)
        out.append(
            BistHistoricalPrice(
                symbol=row.symbol,
                trade_date=row.trade_date,
                close=close,
                currency=row.currency,
                series=row.series,
                market=row.market,
                source=row.source,
                source_url=row.source_url,
                source_file=row.source_file,
                observed_at=row.observed_at,
                adjustment_status=STATUS_ADJUSTED if factor != 1 else row.adjustment_status,
                previous_close=row.previous_close,
                reference_price=row.reference_price,
                corporate_action_flag=row.corporate_action_flag,
            )
        )
    return tuple(out), STATUS_ADJUSTED


def window_adjustment_status(
    events: Iterable[OfficialCorporateAction],
    *,
    start: date,
    end: date,
) -> str:
    window = events_in_window(events, start=start, end=end)
    adjusting = price_adjusting_events(window)
    if not adjusting:
        return STATUS_NONE if not window else STATUS_RAW_OK
    if any(official_factor_for_event(item) is None for item in adjusting):
        return STATUS_UNRESOLVED
    return STATUS_ADJUSTED
