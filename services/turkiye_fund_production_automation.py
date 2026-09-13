"""FUND27D1 — Production automation firewall.

Automation may inspect and validate FUND26 transaction intents through the
canonical FUND27B controlled-execution adapter, but it must never grant
execution authority.

Rules:
- scheduled automation is always DRY_RUN;
- manual automation also defaults to DRY_RUN;
- automation cannot request or grant EXECUTE;
- no direct WealthCoreService call;
- no ledger persistence;
- no broker order or trade execution.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.turkiye_fund_controlled_execution import (
    MODE_DRY_RUN,
    build_controlled_execution_artifact,
)


OUTPUT_SCHEMA = "fund27d_production_automation_artifact_1"
OUTPUT_STATUS = "PRODUCTION_AUTOMATION_REVIEW_COMPLETE"

TRIGGER_SCHEDULED = "SCHEDULED"
TRIGGER_MANUAL = "MANUAL"

_ALLOWED_TRIGGERS = frozenset(
    {
        TRIGGER_SCHEDULED,
        TRIGGER_MANUAL,
    }
)


class ProductionAutomationContractError(ValueError):
    """Raised when the FUND27D automation firewall is violated."""


def build_production_automation_artifact(
    fund26_artifact: Mapping[str, Any],
    *,
    trigger: str,
    request_execution: bool = False,
    wealth_core_service: Optional[Any] = None,
) -> dict[str, Any]:
    """Build a production-safe automation review artifact.

    ``wealth_core_service`` is accepted only as a compatibility seam for
    callers/tests. This automation layer never passes it into an execution
    path and never invokes it directly.
    """

    normalized_trigger = str(trigger or "").strip().upper()

    if normalized_trigger not in _ALLOWED_TRIGGERS:
        raise ProductionAutomationContractError(
            "unsupported_automation_trigger"
        )

    if request_execution:
        if normalized_trigger == TRIGGER_SCHEDULED:
            raise ProductionAutomationContractError(
                "scheduled_execution_forbidden"
            )
        raise ProductionAutomationContractError(
            "automation_execution_authority_forbidden"
        )

    controlled_execution = build_controlled_execution_artifact(
        fund26_artifact,
        mode=MODE_DRY_RUN,
        execution_authority=False,
        wealth_core_service=None,
    )

    return {
        "schema": OUTPUT_SCHEMA,
        "status": OUTPUT_STATUS,
        "source_schema": controlled_execution["source_schema"],
        "source_status": controlled_execution["source_status"],
        "trigger": normalized_trigger,
        "mode": MODE_DRY_RUN,
        "execution_authority": False,
        "production_persist": False,
        "research_only": True,
        "controlled_execution": controlled_execution,
        "orders_created": False,
        "trades_executed": False,
    }


__all__ = [
    "OUTPUT_SCHEMA",
    "OUTPUT_STATUS",
    "TRIGGER_SCHEDULED",
    "TRIGGER_MANUAL",
    "ProductionAutomationContractError",
    "build_production_automation_artifact",
]
