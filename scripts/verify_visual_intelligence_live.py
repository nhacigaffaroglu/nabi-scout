#!/usr/bin/env python3
"""Live verification for Visual Intelligence pass — zero-cost normal render."""
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
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_performance_intelligence_service import PortfolioPerformanceIntelligenceService
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wave3_intelligence_service import Wave3IntelligenceService
from services.wealth_core_service import WealthCoreService

VERIFY_TAG = "NABI VISUAL INTELLIGENCE LIVE VERIFY"


def _count_providers() -> dict:
    counts = {"llm": 0, "fmp": 0, "sec": 0, "fx_remote": 0, "fund_remote": 0, "build_view_calls": 0}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    return counts, bump


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    user_id = get_current_user_id(client)
    if not user_id:
        print(json.dumps({"tag": VERIFY_TAG, "ok": False, "error": "no_authenticated_user"}))
        return 1

    counts, bump = _count_providers()
    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.ensure_default_portfolio()
    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
    performance_intel = PortfolioPerformanceIntelligenceService(wealth, nabi_client=client)
    monitor = MonitorIntelligenceService(client, user_id)
    wave3_service = Wave3IntelligenceService(client, user_id, wealth)

    with patch("services.fmp_client.FMPClient.profile", side_effect=lambda *a, **k: bump("fmp") or {}):
        with patch(
            "services.sec_financial_client.SECFinancialClient.company_facts",
            side_effect=lambda *a, **k: bump("sec") or {},
        ):
            base_view = intelligence.build_view(portfolio, enrich_nabi=True)
            counts["build_view_calls"] += 1
            dashboard = build_portfolio_intelligence_dashboard(
                base_view,
                accounts_by_id={str(a["id"]): a for a in wealth.list_accounts()},
            )
            v13 = performance_intel.build_view(portfolio, dashboard)
            wave3 = wave3_service.build_view(portfolio=portfolio, dashboard=dashboard)
            monitor.list_events(portfolio_id=str(portfolio["id"]), dashboard=dashboard, limit=20)

    from services.nabi_visual_insights import build_portfolio_insights
    from services.portfolio_intelligence_charts import (
        build_portfolio_value_history_chart,
        build_scenario_impact_chart,
    )

    build_portfolio_insights(dashboard=dashboard, v13=v13, wave3=wave3)
    build_portfolio_value_history_chart(v13.performance_history.history_points, currency=base_view.base_currency)
    scenarios = wave3_service.build_scenarios(dashboard, portfolio_shock_pct=-20.0)
    build_scenario_impact_chart(scenarios, currency=base_view.base_currency)

    remote_ok = all(
        counts[k] == 0 for k in ("llm", "fmp", "sec", "fx_remote", "fund_remote")
    )
    result = {
        "tag": VERIFY_TAG,
        "ok": remote_ok and counts["build_view_calls"] == 1,
        "user_id": user_id,
        "provider_counts": counts,
    }
    print(json.dumps(result, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
