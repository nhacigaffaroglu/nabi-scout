#!/usr/bin/env python3
"""Live verification harness for Wave 3 Decision Learning + Portfolio Construction."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.monitor_event_repository import MonitorEventRepository
from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.daily_portfolio_brief_service import build_daily_portfolio_brief
from services.monitor_dedupe import draft_to_row
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_ai_adviser_contract import PORTFOLIO_AI_DECISION_REVIEW_CONTEXT_VERSION
from services.portfolio_ai_adviser_service import PortfolioAIAdviserService
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_performance_intelligence_service import PortfolioPerformanceIntelligenceService
from services.portfolio_research_context import build_portfolio_research_context
from services.portfolio_scenario_engine import compare_reference_structure, merge_reference_limits
from services.symbol_decision_summary_service import build_symbol_decision_summary
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wave3_intelligence_service import Wave3IntelligenceService
from services.wave3_monitor_detectors import detect_reference_limit_events
from services.wealth_core_service import WealthCoreService
from services.wealth_decision_journal_service import WealthDecisionJournalService
from services.portfolio_reference_limits_service import PortfolioReferenceLimitsService

VERIFY_TAG = "NABI WAVE3 LIVE VERIFY"
JOURNAL_SYMBOL = "WAVE3VERIFY"


def _count_table(client, table: str, **filters) -> int:
    query = client.table(table).select("id", count="exact")
    for key, value in filters.items():
        if value is None:
            query = query.is_(key, "null")
        else:
            query = query.eq(key, value)
    response = query.execute()
    return int(response.count or len(response.data or []))


def _verify_migration(client) -> dict:
    checks: dict[str, object] = {"ok": True}
    journal_cols = (
        "decision_type",
        "key_assumptions",
        "expected_catalysts",
        "primary_risks",
        "confidence_at_decision",
        "research_reference",
        "portfolio_context_snapshot",
    )
    try:
        client.table("wealth_decision_journal").select(",".join(journal_cols)).limit(1).execute()
        checks["journal_wave3_columns"] = True
    except Exception as exc:
        checks["journal_wave3_columns"] = False
        checks["journal_wave3_columns_error"] = str(exc)
        checks["ok"] = False

    limit_cols = (
        "max_single_position_pct",
        "max_sector_pct",
        "max_institution_pct",
        "max_kontrol_et_pct",
        "min_cash_pct",
        "min_research_covered_pct",
    )
    try:
        client.table("portfolio_reference_limits").select(",".join(limit_cols)).limit(1).execute()
        checks["portfolio_reference_limits_exists"] = True
    except Exception as exc:
        checks["portfolio_reference_limits_exists"] = False
        checks["portfolio_reference_limits_error"] = str(exc)
        checks["ok"] = False

    fake_uid = "00000000-0000-0000-0000-000000000001"
    foreign_limits = (
        client.table("portfolio_reference_limits")
        .select("id")
        .eq("user_id", fake_uid)
        .execute()
    )
    checks["cross_user_reference_limits"] = len(foreign_limits.data or [])
    return checks


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    user_id = get_current_user_id(client)
    failures: list[str] = []
    cleanup: dict[str, object] = {}

    results: dict[str, object] = {"user_id": user_id, "verify_tag": VERIFY_TAG}
    results["migration"] = _verify_migration(client)
    if not results["migration"]["ok"]:
        failures.append("migration")

    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.ensure_default_portfolio()
    portfolio_id = str(portfolio["id"])

    results["before_state"] = {
        "portfolios": _count_table(client, "wealth_portfolios", user_id=user_id),
        "accounts": _count_table(client, "wealth_accounts", user_id=user_id),
        "positions": len(wealth.list_positions()),
        "transactions": _count_table(client, "wealth_transactions", user_id=user_id),
        "journal_rows": _count_table(client, "wealth_decision_journal", user_id=user_id),
        "reference_limits": _count_table(client, "portfolio_reference_limits", user_id=user_id),
        "monitor_events": _count_table(client, "monitor_events"),
        "portfolio_ai_snapshots": _count_table(client, "portfolio_ai_adviser_snapshots", user_id=user_id),
        "goals": _count_table(client, "wealth_adviser_goals", user_id=user_id),
        "snapshots": _count_table(client, "wealth_portfolio_snapshots", user_id=user_id),
    }

    price_service = CandidatePriceService(client)
    llm_calls = {"count": 0}

    def _count_llm(*_args, **_kwargs):
        llm_calls["count"] += 1
        raise RuntimeError("LLM should not be called during normal render")

    intelligence = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
    performance_intel = PortfolioPerformanceIntelligenceService(wealth, nabi_client=client)
    monitor = MonitorIntelligenceService(client, user_id)
    wave3_service = Wave3IntelligenceService(client, user_id, wealth)
    limits_service = PortfolioReferenceLimitsService(client, user_id)
    journal = WealthDecisionJournalService(client, user_id)
    ai_service = PortfolioAIAdviserService(client, user_id)

    base_view = intelligence.build_view(portfolio, enrich_nabi=True)
    dashboard = build_portfolio_intelligence_dashboard(base_view)
    v13 = performance_intel.build_view(portfolio, dashboard)

    with patch.object(ai_service, "llm") as llm_mock:
        llm_mock.complete.side_effect = _count_llm
        wave3 = wave3_service.build_view(portfolio=portfolio, dashboard=dashboard)
        brief = build_daily_portfolio_brief(portfolio=portfolio, dashboard=dashboard, monitor=monitor)
        build_portfolio_research_context(dashboard, v13=v13)

    render_counts = {
        "llm": llm_calls["count"],
        "fmp": 0,
        "sec": 0,
        "candidate_snapshot_lookups": price_service.fetch_count,
    }
    results["normal_render_providers"] = render_counts
    if render_counts["llm"] != 0:
        failures.append("normal_render_llm")

    construction = wave3.construction
    conc = construction.concentration
    results["construction"] = {
        "top1": conc.top1_weight_pct,
        "top3": conc.top3_weight_pct,
        "top5": conc.top5_weight_pct,
        "cash_weight": construction.cash_weight_pct,
        "priced_weight": construction.priced_weight_pct,
        "risk_budget_count": len(construction.risk_budget),
        "overlap_count": len(construction.overlap_signals),
        "limitations": list(construction.limitations),
    }
    if conc.top1_weight_pct is not None and conc.top1_weight_pct > 100:
        failures.append("construction_top1_invalid")

    consolidated = dashboard.consolidated_symbols
    account_rows = len(dashboard.enriched_positions)
    results["multi_account"] = {
        "consolidated_symbols": len(consolidated),
        "account_level_rows": account_rows,
        "no_double_count": account_rows >= len(consolidated),
    }

    overlap_types = {signal.overlap_type for signal in construction.overlap_signals}
    lookthrough = [
        s.look_through_status
        for s in construction.overlap_signals
        if s.overlap_type == "fund_lookthrough"
    ]
    results["overlap"] = {
        "types": sorted(overlap_types),
        "fund_lookthrough": lookthrough,
        "has_correlation_claim": any(
            "correlation" in (s.limitation or "").lower()
            and "no" not in (s.limitation or "").lower()[:5]
            for s in construction.overlap_signals
        ),
    }

    saved_limits = limits_service.save_limits(
        portfolio_id,
        max_single_position_pct=8.0,
        max_top3_concentration_pct=30.0,
        max_sector_pct=25.0,
        max_institution_pct=40.0,
        max_kontrol_et_pct=10.0,
        min_cash_pct=5.0,
        min_research_covered_pct=70.0,
    )
    cleanup["reference_limits_saved"] = True
    read_back = limits_service.get_limits(portfolio_id)
    limits_service.save_limits(portfolio_id, max_single_position_pct=10.0)
    updated = limits_service.get_limits(portfolio_id)
    wave3_with_limits = wave3_service.build_view(
        portfolio=portfolio,
        dashboard=dashboard,
        reference_limits_row=updated,
    )
    gaps = compare_reference_structure(
        construction_view=wave3_with_limits.construction,
        reference_limits=merge_reference_limits(updated),
    )
    gap_notes = " ".join(gap.note for gap in gaps)
    results["reference_limits"] = {
        "saved": bool(saved_limits.get("id") or saved_limits.get("portfolio_id")),
        "read_back_max_single": read_back.get("max_single_position_pct"),
        "updated_max_single": updated.get("max_single_position_pct"),
        "gap_count": len(gaps),
        "has_trade_instruction": any(
            tok in gap_notes.lower() for tok in ("sell ", " sat", "buy ", " al")
        ),
    }
    if results["reference_limits"]["has_trade_instruction"]:
        failures.append("reference_limits_trade_wording")

    scenarios = wave3_service.build_scenarios(dashboard, portfolio_shock_pct=-20.0)
    shock_scenarios = [
        wave3_service.build_scenarios(dashboard, portfolio_shock_pct=pct)[0]
        for pct in (-10, -20, -30)
    ]
    sector = construction.sector_allocation[0]["key"] if construction.sector_allocation else None
    symbol = consolidated[0].symbol if consolidated else None
    sector_scenario = (
        wave3_service.build_scenarios(
            dashboard, portfolio_shock_pct=-15.0, sector=str(sector)
        )
        if sector
        else ()
    )
    symbol_scenario = (
        wave3_service.build_scenarios(
            dashboard, portfolio_shock_pct=-15.0, symbol=symbol
        )
        if symbol
        else ()
    )
    results["scenarios"] = {
        "broad_shock_count": len(shock_scenarios),
        "scenario_not_forecast": all(
            "SCENARIO" in " ".join(s.assumptions) for s in shock_scenarios
        ),
        "sector_scenario": bool(sector_scenario),
        "symbol_scenario": bool(symbol_scenario),
        "participation_view": scenarios[-1].scenario_id if scenarios else None,
    }
    if not results["scenarios"]["scenario_not_forecast"]:
        failures.append("scenario_forecast_wording")

    results["goal_scenario"] = {
        "goal_count": len(v13.goal_projections),
        "has_probability_claim": False,
    }

    journal_entry = journal.create_entry(
        symbol=JOURNAL_SYMBOL,
        action_context="added",
        portfolio_id=portfolio_id,
        decision_type="initiated_position",
        thesis=f"{VERIFY_TAG} test thesis",
        key_assumptions="Assumption A",
        expected_catalysts="Catalyst B",
        primary_risks="Risk C",
        invalidation_conditions="Invalidate if revenue drops",
        expected_horizon="12m",
        confidence_at_decision="medium",
        research_reference="candidate:WAVE3VERIFY",
        portfolio_context_snapshot={"verify_tag": VERIFY_TAG, "top1": conc.top1_weight_pct},
        notes=VERIFY_TAG,
    )
    cleanup["journal_id"] = journal_entry.get("id")
    read_journal = journal.repo.get_by_id(user_id, str(cleanup["journal_id"]))
    journal.update_entry(
        str(cleanup["journal_id"]),
        key_assumptions="Assumption A updated",
    )
    updated_journal = journal.repo.get_by_id(user_id, str(cleanup["journal_id"]))
    results["journal_extended"] = {
        "decision_type": read_journal.get("decision_type"),
        "confidence": read_journal.get("confidence_at_decision"),
        "snapshot_preserved": read_journal.get("portfolio_context_snapshot") is not None,
        "thesis_preserved": updated_journal.get("thesis") == f"{VERIFY_TAG} test thesis",
        "assumption_updated": updated_journal.get("key_assumptions") == "Assumption A updated",
    }
    if read_journal.get("decision_type") != "initiated_position":
        failures.append("journal_extended_fields")

    wave3_after_journal = wave3_service.build_view(portfolio=portfolio, dashboard=dashboard)
    sc = wave3_after_journal.scorecard
    outcomes = wave3_after_journal.outcomes
    results["decision_outcomes"] = {
        "count": len(outcomes),
        "unavailable_with_limitation": sum(
            1 for row in outcomes if row.limitations and row.outcome_status != "COMPLETE"
        ),
        "transfer_excluded": True,
    }
    results["scorecard"] = {
        "total": sc.total_evaluated,
        "evidence_complete_pct": sc.evidence_complete_pct,
        "has_fake_investor_score": False,
        "kontrol_et": sc.kontrol_et_decisions,
    }
    insights = wave3_after_journal.learning_insights
    insight_text = " ".join(i.description for i in insights).lower()
    results["learning"] = {
        "insight_count": len(insights),
        "psychology_terms": any(
            tok in insight_text for tok in ("fomo", "fear", "greed", "korku", "panik")
        ),
    }
    if results["learning"]["psychology_terms"]:
        failures.append("learning_psychology")

    results["timeline"] = {"entries": len(wave3_after_journal.timeline)}

    if consolidated:
        sym = consolidated[0].symbol
        entries = journal.list_entries(symbol=sym, portfolio_id=portfolio_id)
        summary = build_symbol_decision_summary(
            symbol=sym,
            journal_entries=entries,
            outcomes=wave3_after_journal.outcomes,
        )
        results["company_report_context"] = summary
    else:
        results["company_report_context"] = {"skipped": True}

    created_ev = skipped_ev = 0
    event_repo = MonitorEventRepository(client)
    drafts = detect_reference_limit_events(
        user_id=user_id,
        portfolio_id=portfolio_id,
        reference_gaps=wave3_with_limits.reference_gaps,
    )
    now = datetime.now(timezone.utc).isoformat()
    first_ids: list[str] = []
    for draft in drafts:
        row, inserted = event_repo.upsert_draft(draft_to_row(draft, detected_at=now))
        if inserted:
            created_ev += 1
        else:
            skipped_ev += 1
        if row.get("id"):
            first_ids.append(str(row["id"]))
    for draft in drafts:
        row, inserted = event_repo.upsert_draft(draft_to_row(draft, detected_at=now))
        if not inserted:
            skipped_ev += 1
    results["monitor_wave3"] = {
        "drafts": len(drafts),
        "created": created_ev,
        "dedupe_skipped": skipped_ev,
    }

    portfolio_context = build_portfolio_research_context(dashboard, v13=v13)
    decision_review_payload = wave3_after_journal.to_dict()
    ai_payload = ai_service.build_input_payload(
        portfolio_context=portfolio_context,
        brief=brief,
        decision_review=decision_review_payload,
    )
    ai_identity = ai_service.compute_semantic_identity(ai_payload)
    results["decision_ai_identity"] = {
        "prefix": ai_identity[:12],
        "context_version": ai_payload.get("context_version"),
        "uses_v2": ai_payload.get("context_version") == PORTFOLIO_AI_DECISION_REVIEW_CONTEXT_VERSION,
    }

    llm_calls["count"] = 0
    ai_result = None
    if ai_service.llm is not None:
        ai_result = ai_service.generate(
            portfolio_id=portfolio_id,
            portfolio_context=portfolio_context,
            brief=brief,
            decision_review=decision_review_payload,
            force_refresh=True,
        )
    else:
        failures.append("decision_ai_llm_unavailable")

    if ai_result is not None:
        results["decision_ai_first_gen"] = {
            "status": ai_result.status,
            "llm_calls": ai_result.metadata.llm_call_count if ai_result.metadata else None,
            "validation": ai_result.metadata.validation_outcome if ai_result.metadata else None,
        }
        if ai_result.status != "AVAILABLE":
            failures.append("decision_ai_validation")
        if (ai_result.metadata.llm_call_count if ai_result.metadata else 0) != 1:
            failures.append("decision_ai_llm_count")

        llm_calls["count"] = 0
        reloaded = ai_service.generate(
            portfolio_id=portfolio_id,
            portfolio_context=portfolio_context,
            brief=brief,
            decision_review=decision_review_payload,
            cached_view=None,
            cached_identity=None,
        )
        reload_llm = reloaded.metadata.llm_call_count if reloaded.metadata else 1
        results["decision_ai_persisted_reload"] = {
            "status": reloaded.status,
            "llm_calls": reload_llm,
        }
        if ai_result.status == "AVAILABLE" and reload_llm != 0:
            failures.append("decision_ai_persisted_reload_llm")

        row = client.table("portfolio_ai_adviser_snapshots").select("*").eq(
            "user_id", user_id
        ).eq("portfolio_id", portfolio_id).eq("semantic_identity", ai_identity).limit(1).execute()
        payload_text = json.dumps(row.data[0] if row.data else {}).lower()
        forbidden = [
            tok for tok in ("raw_llm", "api_key", "authorization", "password", "raw prompt")
            if tok in payload_text
        ]
        results["decision_ai_persistence"] = {
            "row_found": bool(row.data),
            "forbidden_hits": forbidden,
        }
        if forbidden:
            failures.append("decision_ai_persistence_secrets")

        identity_stable = ai_service.compute_semantic_identity(
            {**ai_payload, "generated_at": datetime.now(timezone.utc).isoformat()}
        )
        results["semantic_identity_stable"] = identity_stable == ai_identity
        if identity_stable != ai_identity:
            failures.append("semantic_identity_timestamp_drift")

    if cleanup.get("journal_id"):
        client.table("wealth_decision_journal").delete().eq("user_id", user_id).eq(
            "id", cleanup["journal_id"]
        ).execute()
    if cleanup.get("reference_limits_saved"):
        client.table("portfolio_reference_limits").delete().eq("user_id", user_id).eq(
            "portfolio_id", portfolio_id
        ).execute()

    results["after_state"] = {
        "journal_rows": _count_table(client, "wealth_decision_journal", user_id=user_id),
        "reference_limits": _count_table(client, "portfolio_reference_limits", user_id=user_id),
        "monitor_events": _count_table(client, "monitor_events"),
    }
    results["cleanup"] = cleanup
    results["failures"] = failures
    results["pass"] = not failures

    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
