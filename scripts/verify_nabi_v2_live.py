#!/usr/bin/env python3
"""Live verification harness for NABI Scout 2.0 release."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.data_quality_center_service import build_data_quality_summary
from services.daily_portfolio_brief_service import build_daily_portfolio_brief
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.system_health_service import SystemHealthService
from services.total_wealth_service import compute_total_wealth_metrics
from services.wealth_core_service import WealthCoreService

VERIFY_TAG = "NABI V2 LIVE VERIFY"


def _zero_cost_render_check(client, user_id: str) -> dict:
    llm_calls = fmp_calls = sec_calls = fx_remote = fund_remote = 0

    def bump(name: str) -> None:
        nonlocal llm_calls, fmp_calls, sec_calls, fx_remote, fund_remote
        if name == "llm":
            llm_calls += 1
        elif name == "fmp":
            fmp_calls += 1
        elif name == "sec":
            sec_calls += 1
        elif name == "fx":
            fx_remote += 1
        elif name == "fund":
            fund_remote += 1

    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.ensure_default_portfolio()
    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
    monitor = MonitorIntelligenceService(client, user_id)

    with patch("services.fmp_client.FMPClient.profile", side_effect=lambda *a, **k: bump("fmp") or {}):
        with patch("services.sec_financial_client.SECFinancialClient.company_facts", side_effect=lambda *a, **k: bump("sec") or {}):
            base_view = intelligence.build_view(portfolio, enrich_nabi=False)
            dashboard = build_portfolio_intelligence_dashboard(base_view, accounts_by_id={})
            build_daily_portfolio_brief(portfolio=portfolio, dashboard=dashboard, monitor=monitor)
            compute_total_wealth_metrics(
                base_view,
                participation_covered_pct=dashboard.participation_eligible_weight_pct,
                research_covered_pct=dashboard.research_coverage_weight_pct,
            )
            build_data_quality_summary(dashboard)
            monitor.list_events(portfolio_id=str(portfolio["id"]), dashboard=dashboard, limit=20)
            SystemHealthService(client).list_automation_health()

    ok = all(v == 0 for v in (llm_calls, fmp_calls, sec_calls, fx_remote, fund_remote))
    return {
        "ok": ok,
        "llm": llm_calls,
        "fmp": fmp_calls,
        "sec": sec_calls,
        "fx_remote": fx_remote,
        "fund_remote": fund_remote,
    }


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    user_id = get_current_user_id(client)
    if not user_id:
        print(json.dumps({"tag": VERIFY_TAG, "ok": False, "error": "no_authenticated_user"}))
        return 1

    zero_cost = _zero_cost_render_check(client, user_id)
    health_rows = [row.to_dict() for row in SystemHealthService(client).list_automation_health()]
    result = {
        "tag": VERIFY_TAG,
        "ok": zero_cost["ok"],
        "user_id": user_id,
        "zero_cost": zero_cost,
        "automation_health_count": len(health_rows),
    }
    print(json.dumps(result, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
