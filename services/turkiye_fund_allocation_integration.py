"""FUND25 — Türkiye fund allocation / position-sizing integration.

Pure integration layer between FUND24 deployment eligibility and the existing
canonical new-money allocation engine.

FUND25 does not create another ranking, recommendation, or portfolio-security
decision authority. It adapts deployment-eligible FUND24 candidates to the
existing allocation engine and projects the resulting amount/quantity plan.

No writes, trades, orders, or persistence.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence

from services.portfolio_security_decision_contract import (
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    PortfolioSecurityDecision,
)
from services.wealth_new_money_allocation import allocate_new_money


INPUT_SCHEMA = "fund24_deployment_eligibility_artifact_1"
OUTPUT_SCHEMA = "fund25_allocation_integration_artifact_1"

INPUT_STATUS = "DEPLOYMENT_ELIGIBILITY_COMPLETE"
OUTPUT_STATUS = "ALLOCATION_INTEGRATION_COMPLETE"

STATE_ALLOCATED = "ALLOCATED"
STATE_NOT_ALLOCATED = "NOT_ALLOCATED"
STATE_NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_ALLOCATION"
STATE_BLOCKED = "ALLOCATION_INPUT_BLOCKED"

DEPLOYMENT_ELIGIBLE = "DEPLOYMENT_ELIGIBLE"
DEPLOYMENT_NOT_ELIGIBLE = "NOT_ELIGIBLE_FOR_DEPLOYMENT"
DEPLOYMENT_BLOCKED = "DEPLOYMENT_INPUT_BLOCKED"

DEPLOYABLE_ACTIONS = frozenset(
    {
        DECISION_CONSIDER_NEW_POSITION,
        DECISION_CONSIDER_TOP_UP,
    }
)

ZERO_WRITE_PROOF = {
    "production_writes": 0,
    "trade_actions": 0,
    "orders": 0,
    "portfolio_writes": 0,
    "recommendation_history_writes": 0,
}


class FundAllocationIntegrationContractError(ValueError):
    """Raised when the FUND24→FUND25 contract is invalid."""


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FundAllocationIntegrationContractError(
            f"{field}_must_be_mapping"
        )
    return dict(value)


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise FundAllocationIntegrationContractError(
            f"{field}_must_be_sequence"
        )
    return list(value)


def _decimal_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _assert_upstream_firewall(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema_version") != INPUT_SCHEMA:
        raise FundAllocationIntegrationContractError(
            "fund24_schema_version_invalid"
        )

    if artifact.get("deployment_eligibility_status") != INPUT_STATUS:
        raise FundAllocationIntegrationContractError(
            "fund24_status_invalid"
        )

    if artifact.get("research_only") is not True:
        raise FundAllocationIntegrationContractError(
            "fund24_research_only_required"
        )

    if artifact.get("execution_authority") is not False:
        raise FundAllocationIntegrationContractError(
            "fund24_execution_authority_must_be_false"
        )

    if artifact.get("production_persist") is not False:
        raise FundAllocationIntegrationContractError(
            "fund24_production_persist_must_be_false"
        )


def _validate_eligible_candidate(row: Mapping[str, Any]) -> None:
    code = row.get("fund_code")
    if not isinstance(code, str) or not code:
        raise FundAllocationIntegrationContractError(
            "candidate_fund_code_invalid"
        )

    if row.get("deployment_eligible") is not True:
        raise FundAllocationIntegrationContractError(
            f"deployment_eligible_flag_invalid:{code}"
        )

    action = row.get("deployment_action")
    if action not in DEPLOYABLE_ACTIONS:
        raise FundAllocationIntegrationContractError(
            f"deployment_action_invalid:{code}"
        )

    canonical_decision = row.get("canonical_decision")
    recommendation_action = row.get("recommendation_action")

    if canonical_decision != action or recommendation_action != action:
        raise FundAllocationIntegrationContractError(
            f"deployment_decision_provenance_mismatch:{code}"
        )

    canonical_payload = _as_dict(
        row.get("canonical_decision_payload"),
        field="canonical_decision_payload",
    )

    if canonical_payload.get("decision") != action:
        raise FundAllocationIntegrationContractError(
            f"canonical_payload_decision_mismatch:{code}"
        )

    if canonical_payload.get("exposure_increase_allowed") is not True:
        raise FundAllocationIntegrationContractError(
            f"canonical_exposure_gate_not_allowed:{code}"
        )

    ranks = (
        row.get("decision_rank"),
        row.get("decision_evaluation_source_rank"),
        row.get("canonical_decision_source_rank"),
        row.get("recommendation_source_rank"),
        row.get("deployment_source_rank"),
    )

    if (
        any(not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0 for rank in ranks)
        or len(set(ranks)) != 1
    ):
        raise FundAllocationIntegrationContractError(
            f"allocation_rank_provenance_mismatch:{code}"
        )


def _candidate_for_allocator(
    row: Mapping[str, Any],
    *,
    candidate_inputs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    code = str(row["fund_code"]).strip().upper()
    supplied = candidate_inputs.get(code)

    if supplied is None:
        raise FundAllocationIntegrationContractError(
            f"allocation_candidate_input_missing:{code}"
        )

    candidate = dict(supplied)

    supplied_symbol = str(candidate.get("symbol") or "").strip().upper()
    if supplied_symbol and supplied_symbol != code:
        raise FundAllocationIntegrationContractError(
            f"allocation_candidate_symbol_mismatch:{code}"
        )

    candidate["symbol"] = code

    # Preserve the allocator's legacy opportunity-classification field.
    # FUND24 / canonical 8E remains the actual deployment authority via the
    # separately validated PortfolioSecurityDecision passed to the allocator.
    candidate["fund25_canonical_action"] = row["deployment_action"]

    # Preserve provenance for audit/debug surfaces. The canonical allocation
    # engine may ignore these fields; FUND25 must not.
    candidate["fund25_source_rank"] = row["deployment_source_rank"]
    candidate["fund25_deployment_state"] = row["deployment_state"]
    candidate["fund25_deployment_eligible"] = True

    return candidate


def _decision_for_allocator(
    row: Mapping[str, Any],
    *,
    security_decisions_by_symbol: Mapping[str, PortfolioSecurityDecision],
) -> PortfolioSecurityDecision:
    code = str(row["fund_code"]).strip().upper()
    decision = security_decisions_by_symbol.get(code)

    if decision is None:
        raise FundAllocationIntegrationContractError(
            f"canonical_security_decision_missing:{code}"
        )

    if decision.symbol.strip().upper() != code:
        raise FundAllocationIntegrationContractError(
            f"canonical_security_decision_symbol_mismatch:{code}"
        )

    if decision.decision != row["deployment_action"]:
        raise FundAllocationIntegrationContractError(
            f"canonical_security_decision_action_mismatch:{code}"
        )

    if decision.exposure_increase_allowed is not True:
        raise FundAllocationIntegrationContractError(
            f"canonical_security_decision_exposure_blocked:{code}"
        )

    return decision


def build_fund_allocation_integration_artifact(
    fund24_artifact: Mapping[str, Any],
    *,
    available_amount: Decimal | float | int | str,
    amount_currency: str,
    portfolio_view: Any,
    candidate_inputs: Mapping[str, Mapping[str, Any]],
    security_decisions: Sequence[PortfolioSecurityDecision],
    policy: Any = None,
    conversion: Any = None,
    assets: Optional[Sequence[dict]] = None,
    positions: Optional[Sequence[dict]] = None,
    minimum_trade_amount: Decimal | float | int | str = 0,
    commission: Decimal | float | int | str = 0,
    allocation: Any = None,
    fund_snapshots: Optional[Mapping[str, Any]] = None,
    fund_mandates: Optional[Mapping[str, Any]] = None,
    fund_mandate_provider: Optional[Any] = None,
    canonical_mappings: Optional[Mapping[str, Any]] = None,
    exposure_overrides: Optional[Mapping[str, Any]] = None,
    security_master: Optional[Any] = None,
    identity_service: Optional[Any] = None,
    hybrid_policy: Optional[Any] = None,
    enable_hybrid_exposure_allocation: Optional[bool] = None,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    """Build a pure FUND25 allocation integration artifact."""

    artifact = _as_dict(
        fund24_artifact,
        field="fund24_artifact",
    )
    _assert_upstream_firewall(artifact)

    raw_candidates = _as_list(
        artifact.get("candidates"),
        field="candidates",
    )

    normalized_inputs = {
        str(symbol).strip().upper(): dict(value)
        for symbol, value in candidate_inputs.items()
    }

    decisions_by_symbol: dict[str, PortfolioSecurityDecision] = {}
    for decision in security_decisions:
        symbol = str(decision.symbol or "").strip().upper()
        if not symbol:
            raise FundAllocationIntegrationContractError(
                "canonical_security_decision_symbol_invalid"
            )
        if symbol in decisions_by_symbol:
            raise FundAllocationIntegrationContractError(
                f"duplicate_canonical_security_decision:{symbol}"
            )
        decisions_by_symbol[symbol] = decision

    allocator_candidates: list[dict[str, Any]] = []
    allocator_decisions: list[PortfolioSecurityDecision] = []

    seen_codes: set[str] = set()
    eligible_rows: dict[str, dict[str, Any]] = {}

    for raw in raw_candidates:
        row = _as_dict(raw, field="candidate")
        code = row.get("fund_code")

        if not isinstance(code, str) or not code:
            raise FundAllocationIntegrationContractError(
                "candidate_fund_code_invalid"
            )

        code = code.strip().upper()

        if code in seen_codes:
            raise FundAllocationIntegrationContractError(
                f"duplicate_candidate:{code}"
            )
        seen_codes.add(code)

        state = row.get("deployment_state")

        if state == DEPLOYMENT_ELIGIBLE:
            _validate_eligible_candidate(row)

            allocator_candidates.append(
                _candidate_for_allocator(
                    row,
                    candidate_inputs=normalized_inputs,
                )
            )
            allocator_decisions.append(
                _decision_for_allocator(
                    row,
                    security_decisions_by_symbol=decisions_by_symbol,
                )
            )
            eligible_rows[code] = row

        elif state == DEPLOYMENT_NOT_ELIGIBLE:
            if row.get("deployment_eligible") is not False:
                raise FundAllocationIntegrationContractError(
                    f"deployment_not_eligible_flag_invalid:{code}"
                )

        elif state == DEPLOYMENT_BLOCKED:
            if row.get("deployment_eligible") is not False:
                raise FundAllocationIntegrationContractError(
                    f"deployment_blocked_flag_invalid:{code}"
                )

        else:
            raise FundAllocationIntegrationContractError(
                f"deployment_state_invalid:{code}"
            )

    # Preserve the canonical upstream ordering explicitly. This is not
    # reranking: FUND25 applies the already-established FUND24 source rank
    # before handing candidates to the canonical allocation engine.
    allocator_candidates.sort(
        key=lambda item: item["fund25_source_rank"]
    )

    rank_by_symbol = {
        item["symbol"]: item["fund25_source_rank"]
        for item in allocator_candidates
    }
    allocator_decisions.sort(
        key=lambda item: rank_by_symbol[
            str(item.symbol or "").strip().upper()
        ]
    )

    plan = allocate_new_money(
        available_amount=available_amount,
        amount_currency=amount_currency,
        portfolio_view=portfolio_view,
        policy=policy,
        candidates=allocator_candidates,
        conversion=conversion,
        assets=assets,
        positions=positions,
        minimum_trade_amount=minimum_trade_amount,
        commission=commission,
        allocation=allocation,
        fund_snapshots=fund_snapshots,
        fund_mandates=fund_mandates,
        fund_mandate_provider=fund_mandate_provider,
        canonical_mappings=canonical_mappings,
        exposure_overrides=exposure_overrides,
        security_master=security_master,
        identity_service=identity_service,
        hybrid_policy=hybrid_policy,
        enable_hybrid_exposure_allocation=enable_hybrid_exposure_allocation,
        security_decisions=allocator_decisions,
    )

    recommendations_by_symbol = {
        str(item.symbol or "").strip().upper(): item
        for item in plan.recommendations
    }

    skips_by_symbol: dict[str, list[Any]] = {}
    for item in plan.skipped:
        symbol = str(item.symbol or "").strip().upper()
        skips_by_symbol.setdefault(symbol, []).append(item)

    output_rows: list[dict[str, Any]] = []
    allocated_count = 0
    not_allocated_count = 0
    not_eligible_count = 0
    blocked_count = 0

    for raw in raw_candidates:
        row = _as_dict(raw, field="candidate")
        code = str(row["fund_code"]).strip().upper()
        out = dict(row)

        if row.get("deployment_state") == DEPLOYMENT_ELIGIBLE:
            recommendation = recommendations_by_symbol.get(code)

            if recommendation is not None:
                allocated_count += 1
                out.update(
                    {
                        "allocation_state": STATE_ALLOCATED,
                        "allocation_eligible": True,
                        "allocated_amount": _decimal_json(
                            recommendation.allocated_amount
                        ),
                        "quantity": _decimal_json(
                            recommendation.quantity
                        ),
                        "allocation_layer": recommendation.layer,
                        "allocation_reason_code": recommendation.reason_code,
                        "allocation_reason": recommendation.reason_text,
                        "allocation_existing_or_new": recommendation.existing_or_new,
                        "allocation_source_rank": row.get(
                            "deployment_source_rank"
                        ),
                        "allocation_source": "CANONICAL_NEW_MONEY_ENGINE",
                    }
                )
            else:
                not_allocated_count += 1
                out.update(
                    {
                        "allocation_state": STATE_NOT_ALLOCATED,
                        "allocation_eligible": True,
                        "allocated_amount": "0",
                        "quantity": "0",
                        "allocation_layer": None,
                        "allocation_reason_code": None,
                        "allocation_reason": None,
                        "allocation_existing_or_new": None,
                        "allocation_source_rank": row.get(
                            "deployment_source_rank"
                        ),
                        "allocation_source": "CANONICAL_NEW_MONEY_ENGINE",
                    }
                )

            out["allocation_skips"] = [
                _jsonable(item)
                for item in skips_by_symbol.get(code, [])
            ]

        elif row.get("deployment_state") == DEPLOYMENT_BLOCKED:
            blocked_count += 1
            out.update(
                {
                    "allocation_state": STATE_BLOCKED,
                    "allocation_eligible": False,
                    "allocated_amount": None,
                    "quantity": None,
                    "allocation_layer": None,
                    "allocation_reason_code": None,
                    "allocation_reason": None,
                    "allocation_existing_or_new": None,
                    "allocation_source_rank": row.get(
                        "deployment_source_rank"
                    ),
                    "allocation_source": None,
                    "allocation_skips": [],
                }
            )

        else:
            not_eligible_count += 1
            out.update(
                {
                    "allocation_state": STATE_NOT_ELIGIBLE,
                    "allocation_eligible": False,
                    "allocated_amount": None,
                    "quantity": None,
                    "allocation_layer": None,
                    "allocation_reason_code": None,
                    "allocation_reason": None,
                    "allocation_existing_or_new": None,
                    "allocation_source_rank": row.get(
                        "deployment_source_rank"
                    ),
                    "allocation_source": None,
                    "allocation_skips": [],
                }
            )

        # FUND25 remains planning-only.
        out["trade"] = None
        out["order"] = None

        output_rows.append(out)

    timestamp = generated_at or datetime.now(
        timezone.utc
    ).isoformat()

    return {
        "schema_version": OUTPUT_SCHEMA,
        "source_schema_version": INPUT_SCHEMA,
        "generated_at": timestamp,
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "allocation_integration_status": OUTPUT_STATUS,
        "decision_winner": None,
        "recommended_symbol": None,
        "input_amount": _decimal_json(plan.input_amount),
        "currency": plan.currency,
        "total_allocated": _decimal_json(plan.total_allocated),
        "residual_cash": _decimal_json(plan.residual_cash),
        "allocation_limitations": list(plan.limitations),
        "allocation_skips": [
            _jsonable(item)
            for item in plan.skipped
        ],
        "counts": {
            "candidates": len(output_rows),
            "deployment_eligible": len(eligible_rows),
            "allocated": allocated_count,
            "not_allocated": not_allocated_count,
            "not_eligible_for_allocation": not_eligible_count,
            "allocation_inputs_blocked": blocked_count,
        },
        "candidates": output_rows,
        "write_proof": dict(ZERO_WRITE_PROOF),
        "trade": None,
        "order": None,
        "limitations": [
            "FUND25 does not recalculate or override canonical 8E decisions.",
            "FUND25 does not rerank FUND20/FUND21/FUND22/FUND23/FUND24 candidates.",
            "Only FUND24 DEPLOYMENT_ELIGIBLE candidates enter allocation evaluation.",
            "FUND25 delegates amount and quantity sizing to allocate_new_money.",
            "FUND25 does not select a decision winner.",
            "FUND25 does not create trades or orders.",
            "FUND25 does not persist portfolio, recommendation history, or production state.",
        ],
    }
