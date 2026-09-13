from __future__ import annotations

import pytest

from services.turkiye_fund_production_automation import (
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    ProductionAutomationContractError,
    build_production_automation_artifact,
)


class SpyWealthCore:
    def __init__(self):
        self.calls = []

    def post_transaction(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "txn-1", **kwargs}


def _fund26_artifact():
    return {
        "schema": "fund26_wealth_os_integration_artifact_1",
        "status": "WEALTH_OS_INTEGRATION_COMPLETE",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "transaction_intents": [
            {
                "symbol": "AAA",
                "txn_type": "BUY",
                "account_id": "acct-1",
                "asset_id": "asset-1",
                "quantity": 2.0,
                "amount": 200.0,
                "currency": "USD",
                "price": 100.0,
                "executed_at": None,
                "notes": "FUND27D test",
                "source_rank": 1,
                "source_schema": "fund26_wealth_os_integration_artifact_1",
                "source_status": "WEALTH_OS_INTEGRATION_COMPLETE",
                "execution_ready": True,
                "idempotency_key": "fund26:test",
            }
        ],
    }


def test_scheduled_trigger_is_always_dry_run():
    core = SpyWealthCore()

    result = build_production_automation_artifact(
        _fund26_artifact(),
        trigger=TRIGGER_SCHEDULED,
        wealth_core_service=core,
    )

    assert result["trigger"] == TRIGGER_SCHEDULED
    assert result["mode"] == "DRY_RUN"
    assert result["execution_authority"] is False
    assert result["production_persist"] is False
    assert result["research_only"] is True
    assert core.calls == []


def test_scheduled_execution_request_fails_closed():
    with pytest.raises(
        ProductionAutomationContractError,
        match="scheduled_execution_forbidden",
    ):
        build_production_automation_artifact(
            _fund26_artifact(),
            trigger=TRIGGER_SCHEDULED,
            request_execution=True,
        )


def test_manual_trigger_defaults_to_dry_run():
    core = SpyWealthCore()

    result = build_production_automation_artifact(
        _fund26_artifact(),
        trigger=TRIGGER_MANUAL,
        wealth_core_service=core,
    )

    assert result["mode"] == "DRY_RUN"
    assert result["execution_authority"] is False
    assert result["production_persist"] is False
    assert core.calls == []


def test_manual_execution_request_is_not_granted_by_automation_layer():
    core = SpyWealthCore()

    with pytest.raises(
        ProductionAutomationContractError,
        match="automation_execution_authority_forbidden",
    ):
        build_production_automation_artifact(
            _fund26_artifact(),
            trigger=TRIGGER_MANUAL,
            request_execution=True,
            wealth_core_service=core,
        )

    assert core.calls == []


def test_unknown_trigger_fails_closed():
    with pytest.raises(
        ProductionAutomationContractError,
        match="unsupported_automation_trigger",
    ):
        build_production_automation_artifact(
            _fund26_artifact(),
            trigger="CRONISH",
        )


def test_automation_artifact_preserves_controlled_execution_provenance():
    result = build_production_automation_artifact(
        _fund26_artifact(),
        trigger=TRIGGER_SCHEDULED,
    )

    assert result["schema"] == "fund27d_production_automation_artifact_1"
    assert result["status"] == "PRODUCTION_AUTOMATION_REVIEW_COMPLETE"
    assert result["source_schema"] == "fund26_wealth_os_integration_artifact_1"
    assert result["controlled_execution"]["schema"] == (
        "fund27b_controlled_execution_artifact_1"
    )
    assert result["controlled_execution"]["mode"] == "DRY_RUN"
    assert result["orders_created"] is False
    assert result["trades_executed"] is False
