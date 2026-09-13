"""FUND26 — Türkiye fund Portfolio / Wealth OS integration.

Transforms the validated FUND25 allocation artifact into Wealth OS transaction
intents.

Architecture:
    FUND25 Allocation Integration
        -> FUND26 Wealth OS Handoff
        -> WealthCoreService.post_transaction (future execution boundary)

FUND26 does not write wealth_transactions, wealth_positions, orders, trades, or
any production state.  It preserves FUND25 allocation authority and prepares a
lossless, auditable handoff for the canonical Wealth OS ledger service.
"""

from __future__ import annotations

import hashlib
import json

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence


INPUT_SCHEMA = "fund25_allocation_integration_artifact_1"
OUTPUT_SCHEMA = "fund26_wealth_os_integration_artifact_1"

INPUT_STATUS = "ALLOCATION_INTEGRATION_COMPLETE"
OUTPUT_STATUS = "WEALTH_OS_INTEGRATION_COMPLETE"

STATE_READY = "WEALTH_OS_HANDOFF_READY"
STATE_NOT_ALLOCATED = "NOT_ALLOCATED"
STATE_NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_WEALTH_OS_HANDOFF"
STATE_INPUT_BLOCKED = "WEALTH_OS_INPUT_BLOCKED"

TXN_TYPE_BUY = "BUY"


class FundWealthOsIntegrationContractError(ValueError):
    """Raised when the FUND25 -> Wealth OS handoff contract is violated."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FundWealthOsIntegrationContractError(f"{field}_must_be_mapping")
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise FundWealthOsIntegrationContractError(f"{field}_must_be_list")
    return list(value)


def _positive_decimal(value: Any, *, field: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FundWealthOsIntegrationContractError(
            f"{field}_must_be_positive_number"
        ) from exc
    if not out.is_finite() or out <= 0:
        raise FundWealthOsIntegrationContractError(
            f"{field}_must_be_positive_number"
        )
    return out


def _optional_positive_decimal(value: Any, *, field: str) -> Optional[Decimal]:
    if value is None:
        return None
    return _positive_decimal(value, field=field)


def _build_idempotency_key(
    *,
    generated_at: Optional[str],
    symbol: str,
    account_id: Optional[str],
    asset_id: Optional[str],
    quantity: Decimal,
    amount: Decimal,
    currency: str,
    price: Optional[Decimal],
    source_rank: int,
) -> Optional[str]:
    """Build one stable execution identity for one FUND25 allocation run."""
    if not generated_at or not account_id or not asset_id:
        return None

    payload = {
        "source_schema": INPUT_SCHEMA,
        "source_status": INPUT_STATUS,
        "generated_at": generated_at,
        "symbol": symbol,
        "account_id": str(account_id).strip(),
        "asset_id": str(asset_id).strip(),
        "txn_type": TXN_TYPE_BUY,
        "quantity": str(quantity),
        "amount": str(amount),
        "currency": currency,
        "price": str(price) if price is not None else None,
        "source_rank": source_rank,
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"fund26:{digest}"


def _assert_fund25_firewall(artifact: Mapping[str, Any]) -> None:
    schema = artifact.get("schema_version", artifact.get("schema"))
    status = artifact.get(
        "allocation_integration_status",
        artifact.get("status"),
    )

    if schema != INPUT_SCHEMA:
        raise FundWealthOsIntegrationContractError("fund25_schema_mismatch")
    if status != INPUT_STATUS:
        raise FundWealthOsIntegrationContractError("fund25_status_mismatch")
    if artifact.get("research_only") is not True:
        raise FundWealthOsIntegrationContractError(
            "fund25_research_only_must_be_true"
        )
    if artifact.get("execution_authority") is not False:
        raise FundWealthOsIntegrationContractError(
            "fund25_execution_authority_must_be_false"
        )
    if artifact.get("production_persist") is not False:
        raise FundWealthOsIntegrationContractError(
            "fund25_production_persist_must_be_false"
        )


def _source_rank(row: Mapping[str, Any]) -> int:
    ranks = []
    for field in (
        "decision_rank",
        "decision_evaluation_source_rank",
        "canonical_decision_source_rank",
        "recommendation_source_rank",
        "deployment_source_rank",
    ):
        value = row.get(field)
        if value is not None:
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise FundWealthOsIntegrationContractError(
                    f"{field}_must_be_positive_int"
                )
            ranks.append(value)

    fund25_rank = row.get("allocation_source_rank")
    if fund25_rank is not None:
        if (
            not isinstance(fund25_rank, int)
            or isinstance(fund25_rank, bool)
            or fund25_rank <= 0
        ):
            raise FundWealthOsIntegrationContractError(
                "allocation_source_rank_must_be_positive_int"
            )
        ranks.append(fund25_rank)

    if not ranks:
        raise FundWealthOsIntegrationContractError(
            "fund25_source_rank_missing"
        )
    if len(set(ranks)) != 1:
        raise FundWealthOsIntegrationContractError(
            "fund25_source_rank_provenance_mismatch"
        )
    return ranks[0]


def _validate_allocated_row(row: Mapping[str, Any]) -> tuple[str, Decimal, Decimal]:
    symbol = str(row.get("fund_code") or row.get("symbol") or "").strip().upper()
    if not symbol:
        raise FundWealthOsIntegrationContractError("fund_code_missing")

    quantity = _positive_decimal(
        row.get("quantity"),
        field=f"{symbol}_quantity",
    )
    amount = _positive_decimal(
        row.get("allocated_amount"),
        field=f"{symbol}_allocated_amount",
    )
    return symbol, quantity, amount


def build_fund_wealth_os_integration_artifact(
    fund25_artifact: Mapping[str, Any],
    *,
    account_id: Optional[str] = None,
    asset_ids_by_symbol: Optional[Mapping[str, str]] = None,
    executed_at: Optional[str] = None,
) -> dict[str, Any]:
    """Build a non-executing Wealth OS handoff from a FUND25 artifact.

    ``account_id`` and ``asset_ids_by_symbol`` are references only.  Their
    presence makes an intent ready for a future WealthCoreService call; FUND26
    itself never calls that service or persists anything.
    """

    artifact = _as_dict(fund25_artifact, field="fund25_artifact")
    _assert_fund25_firewall(artifact)

    rows_value = artifact.get("candidates")
    if rows_value is None:
        rows_value = artifact.get("rows")
    rows = _as_list(rows_value, field="fund25_rows")
    source_generated_at = (
        str(artifact.get("generated_at") or "").strip()
        or None
    )

    asset_map = {
        str(key).strip().upper(): str(value).strip()
        for key, value in dict(asset_ids_by_symbol or {}).items()
        if str(key).strip() and str(value).strip()
    }

    output_rows: list[dict[str, Any]] = []
    transaction_intents: list[dict[str, Any]] = []

    for raw in rows:
        row = _as_dict(raw, field="fund25_row")
        symbol = str(
            row.get("fund_code") or row.get("symbol") or ""
        ).strip().upper()

        out = dict(row)
        out["wealth_os_transaction_intent"] = None

        allocation_state = str(row.get("allocation_state") or "").strip()

        if allocation_state != "ALLOCATED":
            if allocation_state == "NOT_ALLOCATED":
                out["wealth_os_state"] = STATE_NOT_ALLOCATED
            elif allocation_state == "ALLOCATION_INPUT_BLOCKED":
                out["wealth_os_state"] = STATE_INPUT_BLOCKED
            else:
                out["wealth_os_state"] = STATE_NOT_ELIGIBLE
            output_rows.append(out)
            continue

        symbol, quantity, amount = _validate_allocated_row(row)
        rank = _source_rank(row)

        currency = str(
            row.get("currency")
            or artifact.get("currency")
            or "TRY"
        ).strip().upper()
        if not currency:
            raise FundWealthOsIntegrationContractError(
                f"{symbol}_currency_missing"
            )

        price = _optional_positive_decimal(
            row.get("price"),
            field=f"{symbol}_price",
        )

        asset_id = asset_map.get(symbol)
        handoff_ready = bool(account_id and asset_id)

        idempotency_key = _build_idempotency_key(
            generated_at=source_generated_at,
            symbol=symbol,
            account_id=account_id,
            asset_id=asset_id,
            quantity=quantity,
            amount=amount,
            currency=currency,
            price=price,
            source_rank=rank,
        )

        intent = {
            "symbol": symbol,
            "txn_type": TXN_TYPE_BUY,
            "account_id": str(account_id).strip() if account_id else None,
            "asset_id": asset_id,
            "quantity": float(quantity),
            "amount": float(amount),
            "currency": currency,
            "price": float(price) if price is not None else None,
            "executed_at": executed_at,
            "source_generated_at": source_generated_at,
            "idempotency_key": idempotency_key,
            "notes": (
                f"NABI FUND26 Wealth OS handoff; "
                f"source_schema={OUTPUT_SCHEMA}; source_rank={rank}"
            ),
            "source_rank": rank,
            "source_schema": OUTPUT_SCHEMA,
            "source_status": OUTPUT_STATUS,
            "execution_ready": handoff_ready,
        }

        out["wealth_os_state"] = (
            STATE_READY if handoff_ready else STATE_INPUT_BLOCKED
        )
        out["wealth_os_transaction_intent"] = intent
        output_rows.append(out)
        transaction_intents.append(intent)

    return {
        "schema": OUTPUT_SCHEMA,
        "status": OUTPUT_STATUS,
        "source_schema": INPUT_SCHEMA,
        "source_status": INPUT_STATUS,
        "rows": output_rows,
        "transaction_intents": transaction_intents,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "wealth_transactions_written": False,
        "wealth_positions_written": False,
        "orders_created": False,
        "trades_executed": False,
        "limitations": [
            "FUND26 prepares Wealth OS transaction intents only.",
            "FUND26 does not call WealthCoreService.post_transaction.",
            "FUND26 does not write wealth_transactions or wealth_positions.",
            "Execution and production hardening remain downstream responsibilities.",
        ],
    }


__all__ = [
    "INPUT_SCHEMA",
    "OUTPUT_SCHEMA",
    "INPUT_STATUS",
    "OUTPUT_STATUS",
    "STATE_READY",
    "STATE_NOT_ALLOCATED",
    "STATE_NOT_ELIGIBLE",
    "STATE_INPUT_BLOCKED",
    "FundWealthOsIntegrationContractError",
    "build_fund_wealth_os_integration_artifact",
]
