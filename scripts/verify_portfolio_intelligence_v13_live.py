#!/usr/bin/env python3
"""Live verification harness for Portfolio Intelligence v1.3."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.wealth_portfolio_snapshot_repository import (  # noqa: E402
    WealthPortfolioSnapshotRepository,
)
from services.auth_service import get_current_user_id  # noqa: E402
from services.candidate_price_service import CandidatePriceService  # noqa: E402
from services.portfolio_context_service import build_symbol_portfolio_context  # noqa: E402
from services.portfolio_intelligence_enrichment_service import (  # noqa: E402
    build_portfolio_intelligence_dashboard,
)
from services.portfolio_intelligence_service import PortfolioIntelligenceService  # noqa: E402
from services.portfolio_management_service import PortfolioManagementService  # noqa: E402
from services.portfolio_performance_intelligence_service import (  # noqa: E402
    PortfolioPerformanceIntelligenceService,
)
from services.portfolio_research_context import (  # noqa: E402
    assert_portfolio_research_context_safe,
    build_portfolio_research_context,
)
from services.supabase_admin_client import (  # noqa: E402
    apply_local_secrets_to_env,
    create_admin_supabase_client,
)
from services.wealth_adviser_profile_service import WealthAdviserGoalService  # noqa: E402
from services.wealth_core_service import WealthCoreService  # noqa: E402
from services.wealth_decision_journal_service import WealthDecisionJournalService  # noqa: E402
from services.wealth_timeline_service import WealthTimelineService  # noqa: E402

VERIFY_TAG = "NABI V13 LIVE VERIFY"
VERIFY_GOAL_TITLE = f"{VERIFY_TAG} GOAL"
VERIFY_JOURNAL_SYMBOL = "AAPL"
VERIFY_JOURNAL_THESIS = f"{VERIFY_TAG} thesis"


def _wealth_state(wealth: WealthCoreService, portfolio_id: str) -> dict:
    return {
        "portfolio_id": portfolio_id,
        "accounts": len(wealth.list_accounts()),
        "positions": len(wealth.list_positions()),
        "transactions": len(wealth.list_transactions(limit=5000)),
        "goals": len(
            wealth.client.table("wealth_adviser_goals")
            .select("id")
            .eq("user_id", wealth.user_id)
            .execute()
            .data
            or []
        ),
        "journal": len(
            wealth.client.table("wealth_decision_journal")
            .select("id")
            .eq("user_id", wealth.user_id)
            .execute()
            .data
            or []
        ),
        "snapshots": len(
            wealth.client.table("wealth_portfolio_snapshots")
            .select("id")
            .eq("user_id", wealth.user_id)
            .eq("portfolio_id", portfolio_id)
            .execute()
            .data
            or []
        ),
    }


def _verify_migrations(client, user_id: str) -> dict:
    checks: dict[str, object] = {}
    journal_ok = False
    goal_cols_ok = False
    try:
        client.table("wealth_decision_journal").select("id").limit(1).execute()
        journal_ok = True
    except Exception as exc:
        checks["journal_error"] = str(exc)

    try:
        client.table("wealth_adviser_goals").select(
            "monthly_contribution_assumption,"
            "expected_annual_return_assumption,"
            "assumption_notes"
        ).limit(1).execute()
        goal_cols_ok = True
    except Exception as exc:
        checks["goal_columns_error"] = str(exc)

    fake_uid = "00000000-0000-0000-0000-000000000001"
    foreign_journal = (
        client.table("wealth_decision_journal")
        .select("id")
        .eq("user_id", fake_uid)
        .execute()
    )
    checks.update(
        {
            "wealth_decision_journal_exists": journal_ok,
            "goal_projection_columns_exist": goal_cols_ok,
            "journal_cross_user_rows": len(foreign_journal.data or []),
        }
    )
    checks["migrations_ok"] = journal_ok and goal_cols_ok
    return checks


def _count_snapshots_for_today(
    client,
    user_id: str,
    portfolio_id: str,
) -> tuple[int, list[str]]:
    rows = (
        client.table("wealth_portfolio_snapshots")
        .select("id,captured_at")
        .eq("user_id", user_id)
        .eq("portfolio_id", portfolio_id)
        .execute()
        .data
        or []
    )
    today = date.today()
    ids: list[str] = []
    for row in rows:
        captured = str(row.get("captured_at") or "")
        if not captured:
            continue
        if WealthPortfolioSnapshotRepository.utc_date_from_captured_at(captured) == today:
            ids.append(str(row["id"]))
    return len(ids), ids


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    user_id = get_current_user_id(client)
    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.ensure_default_portfolio()
    portfolio_id = str(portfolio["id"])

    results: dict[str, object] = {
        "user_id": user_id,
        "portfolio_id": portfolio_id,
        "verify_tag": VERIFY_TAG,
    }
    failures: list[str] = []
    cleanup: dict[str, object] = {"reversed_txn_ids": [], "archived_goal_id": None}

    results["migration_verification"] = _verify_migrations(client, user_id)
    if not results["migration_verification"]["migrations_ok"]:
        failures.append("migration_verification")

    results["before_state"] = _wealth_state(wealth, portfolio_id)

    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(
        wealth,
        price_service,
        nabi_client=client,
    )
    perf_intel = PortfolioPerformanceIntelligenceService(wealth, nabi_client=client)
    timeline = WealthTimelineService(wealth)
    mgmt = PortfolioManagementService(wealth)

    llm_calls = {"count": 0}
    fmp_calls = {"count": 0}

    def _block_llm(*_a, **_k):
        llm_calls["count"] += 1
        raise RuntimeError("LLM blocked during v1.3 verification")

    def _block_fmp(*_a, **_k):
        fmp_calls["count"] += 1
        raise RuntimeError("FMP blocked during v1.3 verification")

    with patch(
        "services.wealth_adviser_llm_client.requests.post",
        side_effect=_block_llm,
    ), patch(
        "services.fmp_client.FMPClient.quote",
        side_effect=_block_fmp,
    ):
        base_view = intelligence.build_view(portfolio, enrich_nabi=True)
        dashboard = build_portfolio_intelligence_dashboard(base_view)
        v13 = perf_intel.build_view(portfolio, dashboard)

    results["provider_safety"] = {
        "llm_calls": llm_calls["count"],
        "fmp_calls": fmp_calls["count"],
        "sec_calls": 0,
        "price_provider": base_view.price_provider,
    }
    if llm_calls["count"] or fmp_calls["count"]:
        failures.append("provider_safety")

    perf = v13.performance
    results["performance"] = {
        "current_value": perf.current_value,
        "invested_capital": perf.invested_capital,
        "net_contributions": perf.net_contributions,
        "unrealized_pl": perf.unrealized_pl,
        "dividend_income": perf.dividend_income,
        "fee_total": perf.fee_total,
        "investment_gain": perf.investment_gain,
        "performance_available": perf.performance_available,
        "limitations": list(perf.limitations),
    }

    results["cash_flow"] = {
        "deposits": v13.cash_flow.total_deposits,
        "withdrawals": v13.cash_flow.total_withdrawals,
        "net_external_flow": v13.cash_flow.net_external_flow,
        "fees": v13.cash_flow.total_fees,
        "dividends": v13.cash_flow.total_dividends,
    }

    results["income"] = {
        "total_dividends": v13.income.total_dividends,
        "dividends_ytd": v13.income.dividends_ytd,
        "by_symbol_count": len(v13.income.by_symbol),
    }

    before_today_count, _ = _count_snapshots_for_today(client, user_id, portfolio_id)
    snap1 = timeline.save_snapshot_from_view(portfolio, base_view)
    snap2 = timeline.save_snapshot_from_view(portfolio, base_view)
    after_today_count, today_ids = _count_snapshots_for_today(
        client, user_id, portfolio_id
    )
    results["snapshot_idempotency"] = {
        "before_today_count": before_today_count,
        "after_today_count": after_today_count,
        "same_snapshot_id": snap1.id == snap2.id,
        "today_snapshot_ids": today_ids,
        "increment_at_most_one": after_today_count <= before_today_count + 1,
    }
    if not results["snapshot_idempotency"]["same_snapshot_id"]:
        failures.append("snapshot_idempotency_same_id")
    if not results["snapshot_idempotency"]["increment_at_most_one"]:
        failures.append("snapshot_idempotency_duplicate_rows")

    results["what_changed"] = {
        "event_count": len(v13.change_events),
        "sample_titles": [event.title for event in v13.change_events[:5]],
        "insufficient_history": len(timeline.list_snapshots(portfolio_id)) < 2,
    }

    results["attention"] = [
        {"code": item.code, "severity": item.severity, "title": item.title}
        for item in dashboard.attention_items
    ]

    forbidden_words = ("buy", "sell", "strong buy", "target price")
    opp_rows = []
    for row in v13.opportunities[:10]:
        label = str(row.opportunity_label or "").lower()
        detail = str(row.explanation or "").lower()
        if any(word in label or word in detail for word in forbidden_words):
            failures.append(f"opportunity_forbidden_wording:{row.symbol}")
        opp_rows.append(
            {
                "symbol": row.symbol,
                "label": row.opportunity_label,
                "sector": row.sector,
            }
        )
    results["opportunities"] = opp_rows

    accounts = wealth.list_accounts()
    cash_account = next(
        (row for row in accounts if str(row.get("account_type") or "").lower() == "cash"),
        accounts[0] if accounts else None,
    )
    dividend_txn_id = None
    fee_txn_id = None
    deposit_txn_id = None
    if cash_account is not None:
        try:
            deposit_txn = mgmt.record_cash_event(
                account_id=str(cash_account["id"]),
                txn_type="deposit",
                amount=5.0,
                currency="USD",
                notes=f"{VERIFY_TAG} deposit for fee test",
            )
            deposit_txn_id = str(deposit_txn["id"])
            div_txn = mgmt.record_cash_event(
                account_id=str(cash_account["id"]),
                txn_type="dividend",
                amount=1.23,
                currency="USD",
                symbol=VERIFY_JOURNAL_SYMBOL,
                notes=VERIFY_TAG,
            )
            dividend_txn_id = str(div_txn["id"])
            fee_txn = mgmt.record_cash_event(
                account_id=str(cash_account["id"]),
                txn_type="fee",
                amount=0.45,
                currency="USD",
                notes=VERIFY_TAG,
            )
            fee_txn_id = str(fee_txn["id"])
            rebuilt = intelligence.build_view(portfolio, enrich_nabi=True)
            rebuilt_dash = build_portfolio_intelligence_dashboard(rebuilt)
            rebuilt_v13 = perf_intel.build_view(portfolio, rebuilt_dash)
            results["dividend_fee_live"] = {
                "dividend_txn_id": dividend_txn_id,
                "fee_txn_id": fee_txn_id,
                "deposit_txn_id": deposit_txn_id,
                "income_total_after": rebuilt_v13.income.total_dividends,
                "fee_total_after": rebuilt_v13.income.fee_total,
            }
            for txn_id in (fee_txn_id, dividend_txn_id, deposit_txn_id):
                if not txn_id:
                    continue
                try:
                    wealth.reverse_transaction(txn_id)
                    cleanup["reversed_txn_ids"].append(txn_id)
                except Exception as exc:
                    failures.append(f"reverse_txn:{txn_id}:{exc}")
        except Exception as exc:
            results["dividend_fee_live"] = {"error": str(exc)}
            failures.append("dividend_fee_live")
            for txn_id in (fee_txn_id, dividend_txn_id, deposit_txn_id):
                if not txn_id:
                    continue
                try:
                    wealth.reverse_transaction(txn_id)
                    cleanup["reversed_txn_ids"].append(txn_id)
                except Exception:
                    pass

    goal_service = WealthAdviserGoalService(client, user_id)
    temp_goal = goal_service.create_goal(
        portfolio_id=portfolio_id,
        goal_type="CUSTOM",
        title=VERIFY_GOAL_TITLE,
        target_date="2030-12-31",
        target_amount=250000.0,
        currency="USD",
        notes=VERIFY_TAG,
    )
    goal_service.update_goal(
        str(temp_goal.id),
        monthly_contribution_assumption=500.0,
        expected_annual_return_assumption=0.07,
        assumption_notes=f"{VERIFY_TAG} user assumption only",
    )
    goal_row = (
        client.table("wealth_adviser_goals")
        .select("*")
        .eq("id", str(temp_goal.id))
        .limit(1)
        .execute()
        .data[0]
    )
    goal_view = intelligence.build_view(portfolio, enrich_nabi=True)
    goal_dash = build_portfolio_intelligence_dashboard(goal_view)
    goal_v13 = perf_intel.build_view(portfolio, goal_dash)
    projections = [
        {
            "title": item.goal_title,
            "scenarios": [
                {
                    "label": scenario.label,
                    "projected_value": scenario.projected_value,
                    "assumptions_note": scenario.assumptions_note,
                }
                for scenario in item.scenarios
            ],
            "progress_pct": item.scenarios[0].progress_pct if item.scenarios else None,
            "funding_gap": item.scenarios[1].funding_gap if len(item.scenarios) > 1 else None,
        }
        for item in goal_v13.goal_projections
        if item.goal_title == VERIFY_GOAL_TITLE
    ]
    results["goal_projection"] = {
        "goal_id": str(temp_goal.id),
        "assumption_columns": {
            "monthly_contribution_assumption": goal_row.get(
                "monthly_contribution_assumption"
            ),
            "expected_annual_return_assumption": goal_row.get(
                "expected_annual_return_assumption"
            ),
            "assumption_notes": goal_row.get("assumption_notes"),
        },
        "projections": projections,
    }
    archived = goal_service.archive_goal(str(temp_goal.id))
    cleanup["archived_goal_id"] = str(archived.id)

    journal = WealthDecisionJournalService(client, user_id)
    entry = journal.create_entry(
        symbol=VERIFY_JOURNAL_SYMBOL,
        action_context="reviewed",
        portfolio_id=portfolio_id,
        thesis=VERIFY_JOURNAL_THESIS,
        key_evidence=f"{VERIFY_TAG} evidence",
        key_risks=f"{VERIFY_TAG} risks",
        invalidation_conditions=f"{VERIFY_TAG} invalidation",
        expected_horizon="medium",
        tags=[VERIFY_TAG],
        notes=VERIFY_TAG,
    )
    updated = journal.update_entry(
        str(entry["id"]),
        thesis=f"{VERIFY_JOURNAL_THESIS} updated",
    )
    read_back = journal.list_entries(
        symbol=VERIFY_JOURNAL_SYMBOL,
        portfolio_id=portfolio_id,
        limit=5,
    )
    results["decision_journal"] = {
        "entry_id": str(entry["id"]),
        "created": entry.get("symbol") == VERIFY_JOURNAL_SYMBOL,
        "updated_thesis": updated.get("thesis"),
        "read_back_count": len(read_back),
    }
    client.table("wealth_decision_journal").delete().eq("user_id", user_id).eq(
        "id", str(entry["id"])
    ).execute()
    cleanup["deleted_journal_id"] = str(entry["id"])

    held_symbol = None
    for row in dashboard.enriched_positions:
        if not row.valuation.is_cash:
            held_symbol = row.valuation.symbol
            break
    held_symbol = held_symbol or VERIFY_JOURNAL_SYMBOL
    portfolio_ctx = build_symbol_portfolio_context(client, user_id, held_symbol)
    results["company_report"] = {
        "held_symbol": held_symbol,
        "held": portfolio_ctx.held if portfolio_ctx else False,
        "weight_pct": portfolio_ctx.portfolio_weight_pct if portfolio_ctx else None,
        "account_rows": len(portfolio_ctx.account_breakdown) if portfolio_ctx else 0,
    }

    context = build_portfolio_research_context(dashboard, v13=v13)
    context_dict = context.to_dict()
    assert_portfolio_research_context_safe(context_dict)
    serialized = json.dumps(context_dict).lower()
    forbidden_hits = [
        token
        for token in (
            "api_key",
            "authorization",
            "bearer",
            "service_role",
            "password",
            "raw_llm",
            "raw_provider",
        )
        if token in serialized
    ]
    results["research_context_v3"] = {
        "schema_version": context.schema_version,
        "has_performance": context.performance is not None,
        "has_income": context.income is not None,
        "change_events": len(context.change_events),
        "goal_projections": len(context.goal_projections),
        "opportunity_candidates": len(context.opportunity_candidates),
        "forbidden_hits": forbidden_hits,
    }
    if forbidden_hits:
        failures.append("research_context_forbidden_keys")

    results["after_state"] = _wealth_state(wealth, portfolio_id)
    results["cleanup"] = cleanup
    results["failures"] = failures
    results["pass"] = not failures

    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
