#!/usr/bin/env python3
"""Production-safe FUND18 portfolio-fit research runner.

Read-only chain:

FUND14A identities
→ current cached official evidence
→ FUND16 candidates
→ FUND17 context
→ canonical Wealth OS portfolio view
→ FUND18 factual evidence
→ FUND18 descriptive research artifact

No network capture, persistence, allocation, 8E invocation, trade or execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from services.candidate_price_service import CandidatePriceService
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.supabase_admin_client import create_admin_supabase_client
from services.turkiye_fund_portfolio_fit_production_evidence import (
    build_production_portfolio_fit_evidence,
)
from services.turkiye_fund_portfolio_fit_effective_assessment import (
    apply_effective_portfolio_fit_assessment_policy,
)
from services.turkiye_fund_portfolio_fit_research import (
    build_evidence_backed_portfolio_fit_research_artifact,
)
from services.wealth_core_service import WealthCoreService


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"JSON object required: {path}")
    return value


def _default_user_id(client: Any) -> str:
    rows = (
        client.table("wealth_portfolios")
        .select("user_id")
        .eq("is_default", True)
        .limit(1)
        .execute()
        .data
        or []
    )

    if not rows or not isinstance(rows[0], dict) or not rows[0].get("user_id"):
        raise SystemExit("default wealth portfolio user_id not found")

    return str(rows[0]["user_id"])


def _canonical_portfolio_view(client: Any, user_id: str) -> Any:
    portfolio = WealthPortfolioRepository(client).get_default_for_user(user_id)

    if portfolio is None:
        raise SystemExit("default wealth portfolio not found")

    wealth = WealthCoreService(client, user_id=user_id)
    price_service = CandidatePriceService(client)

    intelligence = PortfolioIntelligenceService(
        wealth,
        price_service=price_service,
    )

    view = intelligence.build_view(portfolio=portfolio)

    if view is None:
        raise SystemExit("canonical portfolio view unavailable")

    return view


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument("--fund14a-input", type=Path, required=True)
    parser.add_argument("--fund16-input", type=Path, required=True)
    parser.add_argument("--fund17-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)

    parser.add_argument(
        "--freshness-policy-input",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--metric-assessment-policy-input",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--assessment-policy-input",
        type=Path,
        default=None,
    )

    args = parser.parse_args()

    fund14a = _read_json(args.fund14a_input)
    fund16 = _read_json(args.fund16_input)
    fund17 = _read_json(args.fund17_input)

    freshness_policy = (
        _read_json(args.freshness_policy_input)
        if args.freshness_policy_input
        else None
    )

    metric_policy = (
        _read_json(args.metric_assessment_policy_input)
        if args.metric_assessment_policy_input
        else None
    )

    assessment_policy = (
        _read_json(args.assessment_policy_input)
        if args.assessment_policy_input
        else None
    )

    client = create_admin_supabase_client()
    user_id = _default_user_id(client)
    portfolio_view = _canonical_portfolio_view(client, user_id)

    assembled = build_production_portfolio_fit_evidence(
        fund14a,
        fund16,
        fund17,
        portfolio_view,
    )

    artifact = build_evidence_backed_portfolio_fit_research_artifact(
        fund17,
        evidence=assembled["evidence"],
        freshness_policy=freshness_policy,
        metric_assessment_policy=metric_policy,
    )

    if assessment_policy is not None:
        artifact = apply_effective_portfolio_fit_assessment_policy(
            artifact,
            assessment_inputs=assembled["assessment_inputs"],
            assessment_policy=assessment_policy,
        )

    output = {
        "schema_version": "fund18_production_research_run_1",
        "research_only": True,
        "execution_authority": False,
        "production_persist": False,
        "production_writes": 0,
        "evidence_diagnostics": assembled["diagnostics"],
        "assessment_inputs": assembled["assessment_inputs"],
        "fund18": artifact,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(f"OUTPUT={args.output}")
    print(f"CANDIDATES={assembled['diagnostics']['candidate_count']}")
    print(
        "OFFICIAL_EXPOSURES="
        f"{len(assembled['diagnostics']['official_exposure_codes'])}"
    )
    print(
        "QUARANTINED="
        f"{len(assembled['diagnostics']['quarantined_codes'])}"
    )
    print("PRODUCTION_WRITES=0")
    print("EXECUTION_AUTHORITY=False")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
