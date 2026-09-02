"""Generic stock-split / bonus-share ledger semantics. No symbol special-cases."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Optional

from services.wealth_contract import TXN_TYPE_CORPORATE_ACTION, WealthValidationError

ACTION_BONUS_SHARE = "BONUS_SHARE"
ACTION_STOCK_SPLIT = "STOCK_SPLIT"
CORPORATE_ACTION_TYPES = (ACTION_BONUS_SHARE, ACTION_STOCK_SPLIT)
COST_BASIS_UNRESOLVED = "COST_BASIS_UNRESOLVED"
QTY_EPS = 1e-9


@dataclass(frozen=True)
class CorporateActionEvent:
    symbol: str
    action_type: str
    effective_date: str
    ratio: float
    quantity_before: float
    quantity_after: float
    cost_before: float
    cost_after: float
    source: str = ""

    def additional_quantity(self) -> float:
        return self.quantity_after - self.quantity_before

    def adjusted_unit_cost(self) -> float:
        if self.quantity_after <= 0:
            return 0.0
        return self.cost_after / self.quantity_after

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def split_quantity_and_cost(
    *,
    quantity: float,
    total_cost: float,
    ratio: float,
) -> tuple[float, float, float]:
    """Return (quantity_after, total_cost_after, unit_cost_after).

    Total historical acquisition cost is unchanged. Incremental cash is 0.
    """
    qty = float(quantity)
    cost = float(total_cost)
    factor = float(ratio)
    if qty < 0:
        raise WealthValidationError("Kurumsal işlem miktarı negatif olamaz.")
    if cost < 0:
        raise WealthValidationError("Kurumsal işlem maliyeti negatif olamaz.")
    if factor <= 0:
        raise WealthValidationError("Kurumsal işlem oranı sıfırdan büyük olmalı.")
    quantity_after = qty * factor
    unit = cost / quantity_after if quantity_after else 0.0
    return quantity_after, cost, unit


def build_corporate_action_event(
    *,
    symbol: str,
    action_type: str,
    effective_date: str,
    ratio: float,
    quantity_before: float,
    total_cost: float,
    source: str = "",
) -> CorporateActionEvent:
    kind = str(action_type or "").strip().upper()
    if kind not in CORPORATE_ACTION_TYPES:
        raise WealthValidationError(f"Desteklenmeyen kurumsal işlem: {action_type}")
    quantity_after, cost_after, _unit = split_quantity_and_cost(
        quantity=quantity_before,
        total_cost=total_cost,
        ratio=ratio,
    )
    return CorporateActionEvent(
        symbol=str(symbol or "").strip().upper(),
        action_type=kind,
        effective_date=str(effective_date or "").strip()[:10],
        ratio=float(ratio),
        quantity_before=float(quantity_before),
        quantity_after=quantity_after,
        cost_before=float(total_cost),
        cost_after=cost_after,
        source=str(source or ""),
    )


def _event_identity(event: CorporateActionEvent) -> tuple[str, str, str, float]:
    return (event.symbol, event.action_type, event.effective_date, float(event.ratio))


def parse_corporate_action_notes(notes: Any) -> Optional[dict[str, Any]]:
    text = str(notes or "").strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def corporate_action_already_applied(
    transactions: Iterable[Mapping[str, Any]],
    event: CorporateActionEvent,
) -> bool:
    wanted = _event_identity(event)
    for row in transactions:
        if str(row.get("txn_type") or "").strip().lower() != TXN_TYPE_CORPORATE_ACTION:
            continue
        if row.get("reversal_of_id"):
            continue
        payload = parse_corporate_action_notes(row.get("notes")) or {}
        symbol = str(payload.get("symbol") or "").strip().upper()
        action_type = str(payload.get("action_type") or "").strip().upper()
        effective = str(payload.get("effective_date") or row.get("executed_at") or "")[:10]
        try:
            ratio = float(payload.get("ratio") or 0.0)
        except (TypeError, ValueError):
            ratio = 0.0
        if (symbol, action_type, effective, ratio) == wanted:
            return True
    return False


def proposed_corporate_action_row(event: CorporateActionEvent) -> dict[str, Any]:
    """Ledger proposal only. Caller must persist explicitly."""
    additional = event.additional_quantity()
    if additional <= 0:
        raise WealthValidationError("Kurumsal işlem ek miktarı sıfırdan büyük olmalı.")
    return {
        "txn_type": TXN_TYPE_CORPORATE_ACTION,
        "quantity": additional,
        "price": 0.0,
        "amount": 0.0,
        "executed_at": f"{event.effective_date}T00:00:00+00:00",
        "notes": json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True),
    }


def overlay_unresolved_quantity(
    position: Mapping[str, Any],
    *,
    authoritative_quantity: float,
    cost_covered_quantity: float,
) -> dict[str, Any]:
    """Keep proven cost; do not invent cost for surplus shares."""
    covered = float(cost_covered_quantity)
    authoritative = float(authoritative_quantity)
    unresolved = authoritative > covered + QTY_EPS
    updated = dict(position)
    updated["quantity"] = authoritative
    updated["cost_covered_quantity"] = covered
    updated["cost_basis_unresolved"] = unresolved
    if unresolved:
        updated["cost_basis_status"] = COST_BASIS_UNRESOLVED
    return updated
