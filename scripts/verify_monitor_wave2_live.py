#!/usr/bin/env python3
"""Live verification harness for Wave 2 Monitor + Portfolio AI."""
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
from repositories.user_monitor_event_state_repository import UserMonitorEventStateRepository
from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.daily_portfolio_brief_service import build_daily_portfolio_brief
from services.monitor_contract import (
    EVENT_PORTFOLIO_WEIGHT_CHANGED,
    MonitorEventDraft,
)
from services.monitor_dedupe import draft_to_row
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_ai_adviser_service import PortfolioAIAdviserService
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_research_context import assert_portfolio_research_context_safe, build_portfolio_research_context
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wealth_core_service import WealthCoreService
from services.wealth_decision_journal_service import WealthDecisionJournalService

VERIFY_TAG = "NABI WAVE2 LIVE VERIFY"


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
    tables = (
        "monitor_events",
        "user_monitor_event_state",
        "monitor_runs",
        "portfolio_ai_adviser_snapshots",
    )
    for table in tables:
        try:
            client.table(table).select("id").limit(1).execute()
            checks[f"{table}_exists"] = True
        except Exception as exc:
            checks[f"{table}_exists"] = False
            checks[f"{table}_error"] = str(exc)
            checks["ok"] = False

    try:
        client.table("portfolio_ai_adviser_snapshots").select(
            "semantic_identity,context_version,summary_version"
        ).limit(1).execute()
        checks["portfolio_ai_columns"] = True
    except Exception as exc:
        checks["portfolio_ai_columns"] = False
        checks["ok"] = False
        checks["portfolio_ai_columns_error"] = str(exc)

    fake_uid = "00000000-0000-0000-0000-000000000001"
    foreign_ai = (
        client.table("portfolio_ai_adviser_snapshots")
        .select("id")
        .eq("user_id", fake_uid)
        .execute()
    )
    foreign_state = (
        client.table("user_monitor_event_state")
        .select("id")
        .eq("user_id", fake_uid)
        .execute()
    )
    checks["cross_user_ai_rows"] = len(foreign_ai.data or [])
    checks["cross_user_state_rows"] = len(foreign_state.data or [])
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
        "monitor_events": _count_table(client, "monitor_events"),
        "user_monitor_event_state": _count_table(client, "user_monitor_event_state", user_id=user_id),
        "monitor_runs": _count_table(client, "monitor_runs"),
        "portfolio_ai_snapshots": _count_table(client, "portfolio_ai_adviser_snapshots", user_id=user_id),
        "journal_rows": _count_table(client, "wealth_decision_journal", user_id=user_id),
        "positions": len(wealth.list_positions()),
    }

    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
    monitor = MonitorIntelligenceService(client, user_id)
    ai_service = PortfolioAIAdviserService(client, user_id)
    event_repo = MonitorEventRepository(client)
    state_repo = UserMonitorEventStateRepository(client)

    llm_calls = {"count": 0}
    fmp_calls = {"count": 0}
    sec_calls = {"count": 0}

    def _block_fmp(*_a, **_k):
        fmp_calls["count"] += 1
        raise RuntimeError("FMP blocked")

    def _block_sec(*_a, **_k):
        sec_calls["count"] += 1
        raise RuntimeError("SEC blocked")

    original_complete = getattr(ai_service.llm, "complete", None)

    def _count_llm(messages):
        llm_calls["count"] += 1
        if original_complete is None:
            raise RuntimeError("LLM unavailable")
        return original_complete(messages)

    with patch("services.fmp_client.FMPClient.quote", side_effect=_block_fmp):
        base_view = intelligence.build_view(portfolio, enrich_nabi=True)
        dashboard = build_portfolio_intelligence_dashboard(base_view)

    results["monitor_render_providers"] = {
        "llm": 0,
        "fmp": fmp_calls["count"],
        "sec": sec_calls["count"],
        "price_fetches": price_service.fetch_count,
    }
    if fmp_calls["count"] or sec_calls["count"]:
        failures.append("monitor_render_providers")

    created, skipped = monitor.refresh_portfolio_events(portfolio=portfolio, dashboard=dashboard)
    brief = build_daily_portfolio_brief(portfolio=portfolio, dashboard=dashboard, monitor=monitor)
    events = monitor.list_events(portfolio_id=portfolio_id, dashboard=dashboard, limit=50)

    results["event_refresh"] = {"created": created, "skipped": skipped, "listed": len(events)}
    results["daily_brief"] = {
        "event_counts": brief.event_counts,
        "high_priority": len(brief.highest_priority_events),
        "portfolio_affected": len(brief.portfolio_affected_events),
        "limitations": list(brief.limitations),
    }

    dedupe_key = f"{VERIFY_TAG}:dedupe:test"
    draft = MonitorEventDraft(
        user_id=user_id,
        portfolio_id=portfolio_id,
        symbol="AAPL",
        event_type=EVENT_PORTFOLIO_WEIGHT_CHANGED,
        event_category="portfolio",
        severity="info",
        materiality="info",
        occurred_at=datetime.now(timezone.utc).isoformat(),
        dedupe_key=dedupe_key,
        title=f"{VERIFY_TAG} dedupe test",
        summary="Temporary dedupe verification event.",
        evidence_type="live_verify",
        evidence_reference=VERIFY_TAG,
        previous_value="5.0",
        current_value="6.0",
        event_payload={"verify_tag": VERIFY_TAG},
    )
    row1, ins1 = event_repo.upsert_draft(draft_to_row(draft, detected_at=draft.occurred_at))
    row2, ins2 = event_repo.upsert_draft(draft_to_row(draft, detected_at=draft.occurred_at))
    results["dedupe"] = {
        "first_inserted": ins1,
        "second_inserted": ins2,
        "same_id": str(row1.get("id")) == str(row2.get("id")),
        "dedupe_key": dedupe_key,
    }
    cleanup["temp_event_id"] = str(row1.get("id"))
    if ins2 or str(row1.get("id")) != str(row2.get("id")):
        failures.append("dedupe")

    event_id = str(row1.get("id"))
    monitor.mark_reviewed(event_id)
    reviewed = state_repo.get_state(user_id, event_id)
    monitor.dismiss(event_id)
    dismissed = state_repo.get_state(user_id, event_id)
    monitor.restore(event_id)
    restored = state_repo.get_state(user_id, event_id)
    results["review_state"] = {
        "reviewed": reviewed.get("status") if reviewed else None,
        "dismissed": dismissed.get("status") if dismissed else None,
        "restored": restored.get("status") if restored else None,
    }
    if restored.get("status") != "new":
        failures.append("review_state")

    held_event = next(
        (event for event in events if event.portfolio_impact and event.portfolio_impact.held),
        None,
    )
    if held_event:
        impact = held_event.portfolio_impact
        results["portfolio_impact"] = {
            "symbol": held_event.symbol,
            "held": impact.held,
            "weight": impact.portfolio_weight,
            "accounts": impact.account_count,
            "limitations": list(impact.limitations),
        }
    else:
        results["portfolio_impact"] = {"note": "no held-symbol event in feed"}

    journal = WealthDecisionJournalService(client, user_id)
    entry = journal.create_entry(
        symbol="AAPL",
        action_context="reviewed",
        portfolio_id=portfolio_id,
        thesis=f"{VERIFY_TAG} thesis",
        invalidation_conditions="FCF margin materially deteriorates",
        notes=VERIFY_TAG,
    )
    cleanup["journal_id"] = str(entry["id"])
    thesis_rel_event = next((event for event in events if event.symbol == "AAPL"), None)
    if thesis_rel_event and thesis_rel_event.thesis_relevance:
        rel = thesis_rel_event.thesis_relevance.relevance
        results["thesis_relevance"] = {
            "relevance": rel,
            "explanation": thesis_rel_event.thesis_relevance.explanation,
            "invalidated_wording": "invalidated" in thesis_rel_event.thesis_relevance.explanation.lower(),
        }
        if "invalidated" in thesis_rel_event.thesis_relevance.explanation.lower():
            failures.append("thesis_invalidation_wording")

    portfolio_context = build_portfolio_research_context(dashboard)
    ai_payload = ai_service.build_input_payload(portfolio_context=portfolio_context, brief=brief)
    identity = ai_service.compute_semantic_identity(ai_payload)
    assert_portfolio_research_context_safe(portfolio_context.to_dict())

    persisted_before = ai_service.fetch_persisted(portfolio_id=portfolio_id, semantic_identity=identity)
    llm_calls["count"] = 0
    ai_result = None
    if ai_service.llm is not None:
        with patch.object(ai_service.llm, "complete", side_effect=_count_llm):
            ai_result = ai_service.generate(
                portfolio_id=portfolio_id,
                portfolio_context=portfolio_context,
                brief=brief,
                force_refresh=True,
            )
    else:
        results["portfolio_ai"] = {"skipped": True, "reason": "LLM not configured"}
        failures.append("portfolio_ai_llm_unavailable")

    if ai_result is not None:
        results["portfolio_ai_first_gen"] = {
            "status": ai_result.status,
            "llm_calls": llm_calls["count"],
            "validation": ai_result.metadata.validation_outcome if ai_result.metadata else None,
            "has_executive_summary": bool(ai_result.executive_summary),
        }
        if ai_result.status != "AVAILABLE":
            failures.append("portfolio_ai_validation")
        if llm_calls["count"] != 1:
            failures.append("portfolio_ai_first_llm_count")

        llm_calls["count"] = 0
        reloaded = ai_service.generate(
            portfolio_id=portfolio_id,
            portfolio_context=portfolio_context,
            brief=brief,
            cached_view=None,
            cached_identity=None,
        )
        results["portfolio_ai_persisted_reload"] = {
            "status": reloaded.status,
            "llm_calls": llm_calls["count"],
            "cache_hit": reloaded.metadata.cache_hit if reloaded.metadata else False,
        }
        if llm_calls["count"] != 0:
            failures.append("portfolio_ai_persisted_reload_llm")

        row = client.table("portfolio_ai_adviser_snapshots").select("*").eq(
            "user_id", user_id
        ).eq("portfolio_id", portfolio_id).eq("semantic_identity", identity).limit(1).execute()
        payload_text = json.dumps(row.data[0] if row.data else {}).lower()
        forbidden = [tok for tok in ("raw_llm", "api_key", "authorization", "password") if tok in payload_text]
        results["portfolio_ai_persistence"] = {
            "row_found": bool(row.data),
            "forbidden_hits": forbidden,
        }
        if forbidden:
            failures.append("portfolio_ai_persistence_secrets")

    identity2 = ai_service.compute_semantic_identity(
        {**ai_payload, "generated_at": datetime.now(timezone.utc).isoformat()}
    )
    results["semantic_identity"] = {
        "stable_with_timestamp": identity == identity2,
        "identity_prefix": identity[:12],
    }
    if identity != identity2:
        failures.append("semantic_identity_stable")

    from services.monitor_refresh_service import evaluate_scheduled_monitor_run, finish_monitor_run
    from repositories.monitor_run_repository import MonitorRunRepository

    run_repo = MonitorRunRepository(client)
    gate1 = evaluate_scheduled_monitor_run(run_repo, trigger_type="live-verify")
    if not gate1.get("skipped") and gate1.get("run_id"):
        finish_monitor_run(
            run_repo,
            run_id=str(gate1["run_id"]),
            events_created=0,
            events_skipped=0,
            report_payload={"verify_tag": VERIFY_TAG},
        )
    gate2 = evaluate_scheduled_monitor_run(run_repo, trigger_type="live-verify")
    results["scheduler_idempotency"] = {
        "first_skipped": gate1.get("skipped"),
        "second_skipped": gate2.get("skipped"),
        "same_run_id": gate1.get("run_id") == gate2.get("run_id"),
    }
    if not gate2.get("skipped"):
        failures.append("scheduler_idempotency")

    if cleanup.get("journal_id"):
        client.table("wealth_decision_journal").delete().eq("user_id", user_id).eq(
            "id", cleanup["journal_id"]
        ).execute()
    if cleanup.get("temp_event_id"):
        client.table("user_monitor_event_state").delete().eq("user_id", user_id).eq(
            "monitor_event_id", cleanup["temp_event_id"]
        ).execute()
        client.table("monitor_events").delete().eq("id", cleanup["temp_event_id"]).execute()

    results["after_state"] = {
        "monitor_events": _count_table(client, "monitor_events"),
        "user_monitor_event_state": _count_table(client, "user_monitor_event_state", user_id=user_id),
    }
    results["cleanup"] = cleanup
    results["failures"] = failures
    results["pass"] = not failures

    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
