from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set, Tuple

PROPOSED_TXN_SORT_TAIL = "zzzz-proposed"

from services.wealth_contract import (
    TXN_TYPE_BUY,
    TXN_TYPE_DEPOSIT,
    TXN_TYPE_DIVIDEND,
    TXN_TYPE_FEE,
    TXN_TYPE_SELL,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    TXN_TYPE_WITHDRAW,
    WealthValidationError,
)


def _txn_sort_key(row: Dict[str, Any]) -> Tuple[str, str]:
    return (
        str(row.get("executed_at") or ""),
        str(row.get("created_at") or row.get("id") or ""),
    )


def _collect_reversed_original_ids(transactions: Iterable[Dict[str, Any]]) -> Set[str]:
    rows = list(transactions)
    ids_present = {str(row["id"]) for row in rows if row.get("id")}
    return {
        str(row["reversal_of_id"])
        for row in rows
        if row.get("reversal_of_id") and str(row["reversal_of_id"]) in ids_present
    }


def _rows_for_replay(transactions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Exclude reversed originals and their reversal rows from replay.

    A reversed transaction and its reversal cancel as an auditable pair without
    passing through the original row's impossible intermediate state.
    """
    rows = list(transactions)
    reversed_originals = _collect_reversed_original_ids(rows)
    replay_rows: List[Dict[str, Any]] = []
    for row in rows:
        row_id = str(row["id"]) if row.get("id") else ""
        if row_id and row_id in reversed_originals:
            continue
        if row.get("reversal_of_id"):
            continue
        replay_rows.append(row)
    return replay_rows


def _effective_txn_type(row: Dict[str, Any]) -> str:
    txn_type = str(row.get("txn_type") or "").strip().lower()
    if row.get("reversal_of_id"):
        if txn_type in {TXN_TYPE_BUY, TXN_TYPE_SELL}:
            return TXN_TYPE_SELL if txn_type == TXN_TYPE_BUY else TXN_TYPE_BUY
        if txn_type in {TXN_TYPE_DEPOSIT, TXN_TYPE_WITHDRAW}:
            return TXN_TYPE_WITHDRAW if txn_type == TXN_TYPE_DEPOSIT else TXN_TYPE_DEPOSIT
        if txn_type == TXN_TYPE_TRANSFER_OUT:
            return TXN_TYPE_TRANSFER_IN
        if txn_type == TXN_TYPE_TRANSFER_IN:
            return TXN_TYPE_TRANSFER_OUT
        if txn_type == TXN_TYPE_DIVIDEND:
            return TXN_TYPE_FEE
        if txn_type == TXN_TYPE_FEE:
            return TXN_TYPE_DIVIDEND
    return txn_type


def _rows_for_replay_as_of(
    transactions: Iterable[Dict[str, Any]],
    *,
    as_of: str,
) -> List[Dict[str, Any]]:
    cutoff = str(as_of or "")
    filtered: List[Dict[str, Any]] = []
    for row in _rows_for_replay(transactions):
        executed_at = str(row.get("executed_at") or "")
        if executed_at and executed_at > cutoff:
            continue
        filtered.append(row)
    return filtered


def materialize_position_from_transactions_as_of(
    transactions: Iterable[Dict[str, Any]],
    *,
    as_of: str,
) -> Tuple[float, float]:
    """Replay ledger rows up to and including ``as_of`` (ISO timestamp/date)."""
    return materialize_position_from_transactions(
        _rows_for_replay_as_of(transactions, as_of=as_of)
    )


def materialize_positions_by_asset_as_of(
    transactions: Iterable[Dict[str, Any]],
    *,
    as_of: str,
) -> Dict[str, Tuple[float, float]]:
    """Return ``asset_id -> (quantity, average_cost)`` at ``as_of``."""
    by_asset: Dict[str, List[Dict[str, Any]]] = {}
    for row in _rows_for_replay_as_of(transactions, as_of=as_of):
        asset_id = str(row.get("asset_id") or "")
        if not asset_id:
            continue
        by_asset.setdefault(asset_id, []).append(row)
    return {
        asset_id: materialize_position_from_transactions(rows)
        for asset_id, rows in by_asset.items()
    }


def materialize_position_from_transactions(
    transactions: Iterable[Dict[str, Any]],
) -> Tuple[float, float]:
    """Replay append-only ledger rows into current quantity and average cost.

    Reversed originals and their reversal rows are excluded as cancelling pairs.
    BUY.amount is the lot's total acquisition cost (execution notional plus
    any commission). BUY.quantity is share count only; commission never
    increases quantity. ``txn_type=fee`` remains a cash-balance reduction.
    """
    quantity = 0.0
    average_cost = 0.0

    for row in sorted(_rows_for_replay(transactions), key=_txn_sort_key):
        txn_type = _effective_txn_type(row)
        qty = float(row.get("quantity") or 0.0)
        amount = float(row.get("amount") or 0.0)

        if qty < 0:
            raise WealthValidationError("İşlem miktarı negatif olamaz.")

        if txn_type == TXN_TYPE_BUY:
            if qty <= 0:
                raise WealthValidationError("Alış işleminde miktar sıfırdan büyük olmalı.")
            total_cost = (quantity * average_cost) + amount
            quantity += qty
            average_cost = total_cost / quantity if quantity > 0 else 0.0
            continue

        if txn_type == TXN_TYPE_SELL:
            if qty <= 0:
                raise WealthValidationError("Satış işleminde miktar sıfırdan büyük olmalı.")
            if qty > quantity:
                raise WealthValidationError("Satış miktarı mevcut pozisyonu aşıyor.")
            quantity -= qty
            if quantity == 0:
                average_cost = 0.0
            continue

        if txn_type == TXN_TYPE_TRANSFER_OUT:
            if qty <= 0:
                raise WealthValidationError("Transfer çıkışında miktar sıfırdan büyük olmalı.")
            if qty > quantity:
                raise WealthValidationError("Transfer miktarı mevcut pozisyonu aşıyor.")
            quantity -= qty
            if quantity == 0:
                average_cost = 0.0
            continue

        if txn_type == TXN_TYPE_TRANSFER_IN:
            if qty <= 0:
                raise WealthValidationError("Transfer girişinde miktar sıfırdan büyük olmalı.")
            total_cost = (quantity * average_cost) + amount
            quantity += qty
            average_cost = total_cost / quantity if quantity > 0 else 0.0
            continue

        if txn_type in {TXN_TYPE_DEPOSIT, TXN_TYPE_DIVIDEND}:
            units = qty if qty > 0 else amount
            if units <= 0:
                raise WealthValidationError("Yatırma/temettü işleminde miktar gerekli.")
            if quantity == 0:
                quantity = units
                average_cost = 1.0 if txn_type == TXN_TYPE_DEPOSIT else 0.0
            else:
                total_cost = (quantity * average_cost) + (amount if amount > 0 else units)
                quantity += units
                average_cost = total_cost / quantity if quantity > 0 else 0.0
            continue

        if txn_type in {TXN_TYPE_WITHDRAW, TXN_TYPE_FEE}:
            units = qty if qty > 0 else amount
            if units <= 0:
                raise WealthValidationError("Çekme/masraf işleminde miktar gerekli.")
            if units > quantity:
                raise WealthValidationError("Çekme/masraf miktarı mevcut bakiyeyi aşıyor.")
            quantity -= units
            if quantity == 0:
                average_cost = 0.0
            continue

        raise WealthValidationError(f"Desteklenmeyen işlem türü: {txn_type}")

    return quantity, average_cost


def validate_proposed_transaction(
    existing_transactions: Iterable[Dict[str, Any]],
    proposed: Dict[str, Any],
) -> Tuple[float, float]:
    """Replay the ledger including a proposed row that has not been persisted yet."""
    proposed_row = dict(proposed)
    proposed_row.setdefault("created_at", PROPOSED_TXN_SORT_TAIL)
    return materialize_position_from_transactions(
        list(existing_transactions) + [proposed_row],
    )
