from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from services.decision_outcome_contract import (
    ACTION_TO_DECISION_TYPE,
    OUTCOME_STATUS_COMPLETE,
    OUTCOME_STATUS_PARTIAL,
    OUTCOME_STATUS_UNAVAILABLE,
    OUTCOME_STATUS_UNRESOLVED,
    DecisionOutcome,
)
from services.wealth_contract import TRANSFER_TXN_TYPES, TXN_TYPE_BUY, TXN_TYPE_SELL
from services.wealth_position_engine import materialize_positions_by_asset_as_of


def classify_decision_type(entry: Mapping[str, Any]) -> str:
    explicit = str(entry.get("decision_type") or "").strip().lower()
    if explicit:
        return explicit
    action = str(entry.get("action_context") or "").strip().lower()
    return ACTION_TO_DECISION_TYPE.get(action, "held")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _days_between(start: Optional[str], end: Optional[str]) -> Optional[int]:
    start_dt = _parse_ts(start)
    end_dt = _parse_ts(end)
    if start_dt is None or end_dt is None:
        return None
    return max(0, (end_dt.date() - start_dt.date()).days)


def _txn_price(row: Mapping[str, Any]) -> Optional[float]:
    qty = float(row.get("quantity") or 0.0)
    amount = float(row.get("amount") or 0.0)
    if qty > 0 and amount > 0:
        return amount / qty
    return None


def _find_linked_transaction(
    *,
    symbol: str,
    decision_at: str,
    transactions: Iterable[Mapping[str, Any]],
    assets_by_id: Mapping[str, Mapping[str, Any]],
    window_days: int = 14,
) -> Optional[Dict[str, Any]]:
    decision_dt = _parse_ts(decision_at)
    if decision_dt is None:
        return None
    sym = symbol.strip().upper()
    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for row in transactions:
        txn_type = str(row.get("txn_type") or "").strip().lower()
        if txn_type in TRANSFER_TXN_TYPES:
            continue
        asset = assets_by_id.get(str(row.get("asset_id") or ""), {})
        if str(asset.get("symbol") or "").upper() != sym:
            continue
        if txn_type not in {TXN_TYPE_BUY, TXN_TYPE_SELL}:
            continue
        executed_dt = _parse_ts(str(row.get("executed_at") or ""))
        if executed_dt is None:
            continue
        delta = abs((executed_dt.date() - decision_dt.date()).days)
        if delta <= window_days:
            candidates.append((delta, dict(row)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _symbol_current_price(
    symbol: str,
    *,
    enriched_by_symbol: Mapping[str, Mapping[str, Any]],
) -> Optional[float]:
    row = enriched_by_symbol.get(symbol.strip().upper())
    if not row:
        return None
    price = row.get("price")
    return float(price) if price is not None else None


def _symbol_current_quantity(
    symbol: str,
    *,
    enriched_by_symbol: Mapping[str, Mapping[str, Any]],
) -> Optional[float]:
    row = enriched_by_symbol.get(symbol.strip().upper())
    if not row:
        return None
    qty = row.get("total_quantity")
    return float(qty) if qty is not None else None


def _income_for_symbol(
    symbol: str,
    *,
    since: str,
    transactions: Iterable[Mapping[str, Any]],
    assets_by_id: Mapping[str, Mapping[str, Any]],
) -> Tuple[Optional[float], Optional[float]]:
    sym = symbol.strip().upper()
    dividends = 0.0
    fees = 0.0
    found = False
    for row in transactions:
        executed_at = str(row.get("executed_at") or "")
        if executed_at <= since:
            continue
        asset = assets_by_id.get(str(row.get("asset_id") or ""), {})
        if str(asset.get("symbol") or "").upper() != sym:
            continue
        txn_type = str(row.get("txn_type") or "").strip().lower()
        amount = float(row.get("amount") or 0.0)
        if txn_type == "dividend" and amount > 0:
            dividends += amount
            found = True
        if txn_type == "fee" and amount > 0:
            fees += amount
            found = True
    if not found:
        return None, None
    return dividends, fees


def build_decision_outcome(
    *,
    entry: Mapping[str, Any],
    transactions: Iterable[Mapping[str, Any]],
    assets_by_id: Mapping[str, Mapping[str, Any]],
    enriched_by_symbol: Mapping[str, Mapping[str, Any]],
    participation_by_symbol: Optional[Mapping[str, str]] = None,
    as_of: Optional[str] = None,
) -> DecisionOutcome:
    journal_id = str(entry.get("id") or "")
    symbol = str(entry.get("symbol") or "").upper()
    decision_at = str(entry.get("created_at") or "")
    decision_type = classify_decision_type(entry)
    limitations: List[str] = []

    linked = _find_linked_transaction(
        symbol=symbol,
        decision_at=decision_at,
        transactions=transactions,
        assets_by_id=assets_by_id,
    )
    decision_price = _txn_price(linked) if linked else None
    if decision_price is None:
        limitations.append("Karar anı fiyat kanıtı bulunamadı; geçmiş fiyat tahmin edilmedi.")

    positions_as_of = materialize_positions_by_asset_as_of(
        transactions,
        as_of=decision_at or datetime.now(timezone.utc).isoformat(),
    )
    qty_at_decision = None
    if linked and linked.get("asset_id"):
        qty_at_decision, _ = positions_as_of.get(str(linked["asset_id"]), (None, None))
    elif linked:
        qty_at_decision = float(linked.get("quantity") or 0.0) or None

    current_price = _symbol_current_price(symbol, enriched_by_symbol=enriched_by_symbol)
    current_qty = _symbol_current_quantity(symbol, enriched_by_symbol=enriched_by_symbol)
    current_value = (
        current_price * current_qty
        if current_price is not None and current_qty is not None
        else None
    )

    exposure_at_decision = (
        decision_price * qty_at_decision
        if decision_price is not None and qty_at_decision is not None
        else None
    )

    absolute_outcome = None
    percentage_outcome = None
    if decision_price is not None and current_price is not None:
        absolute_outcome = current_price - decision_price
        if decision_price > 0:
            percentage_outcome = ((current_price - decision_price) / decision_price) * 100.0

    dividends, fees = _income_for_symbol(
        symbol,
        since=decision_at,
        transactions=transactions,
        assets_by_id=assets_by_id,
    )

    if decision_type == "reviewed_without_trade" and percentage_outcome is None:
        outcome_status = OUTCOME_STATUS_UNRESOLVED
    elif percentage_outcome is None:
        outcome_status = OUTCOME_STATUS_UNAVAILABLE if not limitations else OUTCOME_STATUS_PARTIAL
    elif limitations:
        outcome_status = OUTCOME_STATUS_PARTIAL
    else:
        outcome_status = OUTCOME_STATUS_COMPLETE

    evidence = "complete" if outcome_status == OUTCOME_STATUS_COMPLETE else (
        "partial" if outcome_status == OUTCOME_STATUS_PARTIAL else "insufficient"
    )

    return DecisionOutcome(
        journal_id=journal_id,
        symbol=symbol,
        decision_date=decision_at,
        decision_type=decision_type,
        action_context=str(entry.get("action_context") or ""),
        account_id=str(entry.get("account_id")) if entry.get("account_id") else None,
        quantity_at_decision=qty_at_decision,
        exposure_value_at_decision=exposure_at_decision,
        decision_price=decision_price,
        current_price=current_price,
        current_value=current_value,
        holding_period_days=_days_between(decision_at, as_of),
        absolute_outcome=absolute_outcome,
        percentage_outcome=percentage_outcome,
        dividend_income=dividends,
        fees_attributable=fees,
        participation_status_at_decision=(participation_by_symbol or {}).get(symbol),
        thesis_at_decision=entry.get("thesis"),
        invalidation_conditions_at_decision=entry.get("invalidation_conditions"),
        research_reference=entry.get("research_reference"),
        confidence_at_decision=entry.get("confidence_at_decision"),
        outcome_status=outcome_status,
        evidence_completeness=evidence,
        limitations=tuple(limitations),
    )


def build_decision_outcomes(
    *,
    journal_entries: Iterable[Mapping[str, Any]],
    transactions: Iterable[Mapping[str, Any]],
    assets_by_id: Mapping[str, Mapping[str, Any]],
    enriched_by_symbol: Mapping[str, Mapping[str, Any]],
    participation_by_symbol: Optional[Mapping[str, str]] = None,
    as_of: Optional[str] = None,
) -> Tuple[DecisionOutcome, ...]:
    as_of_ts = as_of or datetime.now(timezone.utc).isoformat()
    return tuple(
        build_decision_outcome(
            entry=entry,
            transactions=transactions,
            assets_by_id=assets_by_id,
            enriched_by_symbol=enriched_by_symbol,
            participation_by_symbol=participation_by_symbol,
            as_of=as_of_ts,
        )
        for entry in journal_entries
        if str(entry.get("symbol") or "").strip()
    )
