from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from services.portfolio_security_decision_contract import (
    DECISION_CONSIDER_NEW_POSITION,
)
from services.turkiye_fund_recommendation_layer import (
    build_fund_recommendation_layer_artifact,
)
from services.turkiye_fund_deployment_eligibility import (
    build_fund_deployment_eligibility_artifact,
)
from services.turkiye_fund_allocation_integration import (
    build_fund_allocation_integration_artifact,
)
from services.turkiye_fund_wealth_os_integration import (
    build_fund_wealth_os_integration_artifact,
)
from services.turkiye_fund_controlled_execution import (
    MODE_DRY_RUN,
    build_controlled_execution_artifact,
)
from services.turkiye_fund_production_automation import (
    TRIGGER_SCHEDULED,
    build_production_automation_artifact,
)
from services.wealth_new_money_allocation import (
    AllocationPlan,
    AllocationRecommendation,
)
from tests.test_nabi_adviser_8f import _psd
from tests.test_wealth_new_money_allocation import _policy, _view


GENERATED_AT = "2026-09-13T12:00:00+00:00"


def _fund22_artifact() -> dict:
    return {
        "schema_version": "fund22_canonical_decision_integration_artifact_1",
        "source_schema_version":
            "fund21_decision_evaluation_readiness_artifact_1",
        "generated_at": GENERATED_AT,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "canonical_decision_integration_status":
            "CANONICAL_DECISION_INTEGRATION_COMPLETE",
        "decision_winner": None,
        "recommendation": None,
        "allocation": None,
        "counts": {},
        "candidates": [
            {
                "fund_code": "AAA",
                "decision_rank": 1,
                "decision_evaluation_source_rank": 1,
                "canonical_decision_source_rank": 1,
                "canonical_decision_integration_state":
                    "CANONICAL_DECISION_EVALUATED",
                "canonical_decision":
                    DECISION_CONSIDER_NEW_POSITION,
                "canonical_decision_payload": {
                    "symbol": "AAA",
                    "decision": DECISION_CONSIDER_NEW_POSITION,
                    "confidence": "HIGH",
                    "reason_codes": ["ELIGIBLE_TO_INCREASE"],
                    "exposure_increase_allowed": True,
                },
                "canonical_decision_reasons": [
                    "ELIGIBLE_TO_INCREASE"
                ],
                "canonical_snapshot_provenance": {
                    "participation_row_id": "p-1",
                    "participation_methodology_id": "m-1",
                    "participation_methodology_version": "v1",
                    "participation_semantic_identity": "sem-1",
                    "fi_row_id": "fi-1",
                    "fi_as_of_key": "2026-09-13",
                    "fi_facts_version": "facts-v1",
                    "fi_engine_version": "engine-v1",
                },
                "decision_winner": None,
                "recommendation": None,
                "allocation": None,
            }
        ],
        "write_proof": {
            "production_writes": 0,
            "trade_actions": 0,
            "orders": 0,
            "portfolio_writes": 0,
            "eight_e_persistence_writes": 0,
            "new_money_calls": 0,
        },
    }


def _candidate_input() -> dict:
    return {
        "symbol": "AAA",
        "participation_status": "Uygun",
        "research_allowed": True,
        "status": "GÜÇLÜ ADAY",
        "current_price": 10,
        "currency": "TRY",
        "market": "TR",
        "asset_type": "fund",
    }


def _allocation_plan() -> AllocationPlan:
    rec = AllocationRecommendation(
        symbol="AAA",
        layer="fund",
        existing_or_new="new",
        decision=DECISION_CONSIDER_NEW_POSITION,
        price=Decimal("10"),
        price_currency="TRY",
        quantity=Decimal("25"),
        allocated_amount=Decimal("250"),
        reason_code="STRONG_CANDIDATE",
        reason_text="FUND28 deterministic allocation",
    )
    return AllocationPlan(
        input_amount=Decimal("1000"),
        currency="TRY",
        recommendations=(rec,),
        total_allocated=Decimal("250"),
        residual_cash=Decimal("750"),
        skipped=(),
        limitations=(),
    )


def test_fund22_to_fund27d_release_chain_preserves_authority_boundaries():
    fund23 = build_fund_recommendation_layer_artifact(
        _fund22_artifact(),
        generated_at=GENERATED_AT,
    )

    fund24 = build_fund_deployment_eligibility_artifact(
        fund23,
        generated_at=GENERATED_AT,
    )

    decision = _psd(
        "AAA",
        DECISION_CONSIDER_NEW_POSITION,
        increase=True,
    )

    with patch(
        "services.turkiye_fund_allocation_integration.allocate_new_money",
        return_value=_allocation_plan(),
    ):
        fund25 = build_fund_allocation_integration_artifact(
            fund24,
            available_amount=Decimal("1000"),
            amount_currency="TRY",
            portfolio_view=_view([]),
            policy=_policy(equity=100, etf=0),
            candidate_inputs={"AAA": _candidate_input()},
            security_decisions=(decision,),
            generated_at=GENERATED_AT,
        )

    fund26 = build_fund_wealth_os_integration_artifact(
        fund25,
        account_id="account-1",
        asset_ids_by_symbol={"AAA": "asset-1"},
        executed_at="2026-09-13T15:00:00+03:00",
    )

    controlled = build_controlled_execution_artifact(
        fund26,
        mode=MODE_DRY_RUN,
        execution_authority=False,
        wealth_core_service=None,
    )

    automated = build_production_automation_artifact(
        fund26,
        trigger=TRIGGER_SCHEDULED,
        request_execution=False,
        wealth_core_service=None,
    )

    assert fund23["schema_version"] == \
        "fund23_recommendation_layer_artifact_1"
    assert fund24["schema_version"] == \
        "fund24_deployment_eligibility_artifact_1"

    assert fund25["schema_version"] == \
        "fund25_allocation_integration_artifact_1"
    assert fund25["allocation_integration_status"] == \
        "ALLOCATION_INTEGRATION_COMPLETE"

    assert fund26["schema"] == \
        "fund26_wealth_os_integration_artifact_1"
    assert fund26["status"] == "WEALTH_OS_INTEGRATION_COMPLETE"

    assert len(fund26["transaction_intents"]) == 1
    intent = fund26["transaction_intents"][0]

    assert intent["symbol"] == "AAA"
    assert intent["txn_type"] == "BUY"
    assert intent["account_id"] == "account-1"
    assert intent["asset_id"] == "asset-1"
    assert intent["source_rank"] == 1
    assert intent["execution_ready"] is True
    assert intent["idempotency_key"].startswith("fund26:")

    assert controlled["research_only"] is True
    assert controlled["execution_authority"] is False
    assert controlled["production_persist"] is False

    assert automated["research_only"] is True
    assert automated["execution_authority"] is False
    assert automated["production_persist"] is False

    assert automated["controlled_execution"]["execution_authority"] is False
    assert automated["controlled_execution"]["production_persist"] is False

    assert automated["orders_created"] is False
    assert automated["trades_executed"] is False
