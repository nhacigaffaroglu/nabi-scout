"""FUND27B — Controlled Wealth OS execution adapter.

FUND27B accepts validated FUND26 transaction intents and exposes a controlled
execution boundary.

Default behavior is DRY_RUN:
- no WealthCoreService call
- no ledger write
- no order creation
- no trade execution

Even when execution is explicitly requested, the adapter requires an explicit
execution authority gate. The adapter never creates broker orders directly.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


INPUT_SCHEMA = "fund26_wealth_os_integration_artifact_1"
INPUT_STATUS = "WEALTH_OS_INTEGRATION_COMPLETE"
OUTPUT_SCHEMA = "fund27b_controlled_execution_artifact_1"
OUTPUT_STATUS = "CONTROLLED_EXECUTION_COMPLETE"

MODE_DRY_RUN = "DRY_RUN"
MODE_EXECUTE = "EXECUTE"

STATE_READY = "EXECUTION_READY"
STATE_BLOCKED = "EXECUTION_BLOCKED"
STATE_EXECUTED = "EXECUTED"
STATE_DRY_RUN = "DRY_RUN"

TXN_TYPE_BUY = "BUY"


class ControlledExecutionContractError(ValueError):
    """Raised when the FUND27B execution contract is violated."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ControlledExecutionContractError(f"{field}_must_be_mapping")
    return dict(value)


def _require_text(value: Any, *, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ControlledExecutionContractError(f"{field}_missing")
    return result


def _validate_input(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema") != INPUT_SCHEMA:
        raise ControlledExecutionContractError("fund26_schema_mismatch")

    if artifact.get("status") != INPUT_STATUS:
        raise ControlledExecutionContractError("fund26_status_mismatch")

    if artifact.get("research_only") is not True:
        raise ControlledExecutionContractError(
            "fund26_research_only_must_be_true"
        )

    if artifact.get("execution_authority") is not False:
        raise ControlledExecutionContractError(
            "fund26_execution_authority_must_be_false"
        )

    if artifact.get("production_persist") is not False:
        raise ControlledExecutionContractError(
            "fund26_production_persist_must_be_false"
        )


def _validate_intent(intent: Mapping[str, Any]) -> None:
    _require_text(intent.get("symbol"), field="intent_symbol")

    if str(intent.get("txn_type") or "").strip().upper() != TXN_TYPE_BUY:
        raise ControlledExecutionContractError("unsupported_transaction_type")

    _require_text(intent.get("account_id"), field="intent_account_id")
    _require_text(intent.get("asset_id"), field="intent_asset_id")
    _require_text(intent.get("source_schema"), field="intent_source_schema")
    _require_text(intent.get("source_status"), field="intent_source_status")

    if intent.get("source_schema") != INPUT_SCHEMA:
        raise ControlledExecutionContractError("intent_source_schema_mismatch")

    if intent.get("source_status") != INPUT_STATUS:
        raise ControlledExecutionContractError("intent_source_status_mismatch")

    if intent.get("execution_ready") is not True:
        raise ControlledExecutionContractError("intent_not_execution_ready")

    if intent.get("source_rank") is None:
        raise ControlledExecutionContractError("intent_source_rank_missing")

    try:
        source_rank = int(intent["source_rank"])
    except (TypeError, ValueError) as exc:
        raise ControlledExecutionContractError(
            "intent_source_rank_invalid"
        ) from exc

    if source_rank <= 0:
        raise ControlledExecutionContractError("intent_source_rank_invalid")


def build_controlled_execution_artifact(
    fund26_artifact: Mapping[str, Any],
    *,
    mode: str = MODE_DRY_RUN,
    execution_authority: bool = False,
    wealth_core_service: Optional[Any] = None,
) -> dict[str, Any]:
    """Validate FUND26 intents and optionally cross the controlled boundary.

    ``DRY_RUN`` never calls WealthCoreService.

    ``EXECUTE`` requires:
    - explicit execution authority;
    - a supplied WealthCoreService;
    - valid FUND26 execution-ready intents.

    The actual ledger operation remains delegated to the canonical
    WealthCoreService.post_transaction method.
    """

    artifact = _as_dict(fund26_artifact, field="fund26_artifact")
    _validate_input(artifact)

    normalized_mode = str(mode or MODE_DRY_RUN).strip().upper()
    if normalized_mode not in {MODE_DRY_RUN, MODE_EXECUTE}:
        raise ControlledExecutionContractError("unsupported_execution_mode")

    intents = artifact.get("transaction_intents")
    if not isinstance(intents, (list, tuple)):
        raise ControlledExecutionContractError(
            "transaction_intents_must_be_list"
        )

    output_intents: list[dict[str, Any]] = []
    executed_transactions: list[dict[str, Any]] = []

    for raw_intent in intents:
        intent = _as_dict(raw_intent, field="transaction_intent")
        _validate_intent(intent)

        output = dict(intent)
        output["execution_state"] = STATE_DRY_RUN

        if normalized_mode == MODE_EXECUTE:
            if execution_authority is not True:
                raise ControlledExecutionContractError(
                    "explicit_execution_authority_required"
                )

            if wealth_core_service is None:
                raise ControlledExecutionContractError(
                    "wealth_core_service_required"
                )

            transaction = wealth_core_service.post_transaction(
                account_id=str(intent["account_id"]),
                asset_id=str(intent["asset_id"]),
                txn_type=str(intent["txn_type"]),
                quantity=float(intent["quantity"]),
                amount=float(intent["amount"]),
                currency=str(intent["currency"]),
                price=(
                    float(intent["price"])
                    if intent.get("price") is not None
                    else None
                ),
                executed_at=intent.get("executed_at"),
                notes=intent.get("notes"),
                idempotency_key=_require_text(
                    intent.get("idempotency_key"),
                    field="intent_idempotency_key",
                ),
            )

            output["execution_state"] = STATE_EXECUTED
            output["wealth_transaction"] = transaction
            executed_transactions.append(transaction)

        output_intents.append(output)

    if normalized_mode == MODE_EXECUTE:
        status_state = (
            STATE_EXECUTED if executed_transactions else STATE_BLOCKED
        )
    else:
        status_state = STATE_DRY_RUN

    return {
        "schema": OUTPUT_SCHEMA,
        "status": OUTPUT_STATUS,
        "source_schema": INPUT_SCHEMA,
        "source_status": INPUT_STATUS,
        "mode": normalized_mode,
        "execution_authority": (
            True if normalized_mode == MODE_EXECUTE else False
        ),
        "production_persist": (
            True if normalized_mode == MODE_EXECUTE else False
        ),
        "research_only": normalized_mode == MODE_DRY_RUN,
        "state": status_state,
        "intents": output_intents,
        "executed_transactions": executed_transactions,
        "orders_created": False,
        "trades_executed": False,
    }


__all__ = [
    "INPUT_SCHEMA",
    "OUTPUT_SCHEMA",
    "INPUT_STATUS",
    "OUTPUT_STATUS",
    "MODE_DRY_RUN",
    "MODE_EXECUTE",
    "STATE_READY",
    "STATE_BLOCKED",
    "STATE_EXECUTED",
    "STATE_DRY_RUN",
    "ControlledExecutionContractError",
    "build_controlled_execution_artifact",
]
