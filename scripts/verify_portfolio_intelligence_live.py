#!/usr/bin/env python3
"""Phase 17 live verification harness for Portfolio Intelligence v1.2."""
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
from services.participation_filter_service import (
    COMPANY_REPORT_PARTICIPATION_FILTERS,
    filter_candidates_by_participation,
)
from services.portfolio_context_service import build_symbol_portfolio_context
from services.portfolio_intelligence_charts import (
    build_allocation_bar_chart,
    build_pl_by_position_chart,
    build_position_allocation_chart,
)
from services.portfolio_intelligence_enrichment_service import (
    build_portfolio_intelligence_dashboard,
)
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_research_context import (
    assert_portfolio_research_context_safe,
    build_context_from_view,
)
from services.supabase_admin_client import (
    apply_local_secrets_to_env,
    create_admin_supabase_client,
)
from services.wealth_core_service import WealthCoreService
from services.wealth_exposure_bridge import build_wealth_exposure_context


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    user_id = get_current_user_id(client)
    results: dict[str, object] = {"user_id": user_id}

    wealth = WealthCoreService(client, user_id)
    portfolio_before = wealth.ensure_default_portfolio()
    positions_before = wealth.list_positions()
    results["portfolio_before"] = {
        "id": portfolio_before.get("id"),
        "name": portfolio_before.get("name"),
        "position_count": len(positions_before),
    }

    price_service = CandidatePriceService(client)
    intelligence = PortfolioIntelligenceService(
        wealth,
        price_service,
        nabi_client=client,
    )

    llm_calls = {"count": 0}
    fmp_calls = {"count": 0}

    def _block_llm(*_a, **_k):
        llm_calls["count"] += 1
        raise RuntimeError("LLM call blocked during verification")

    def _block_fmp(*_a, **_k):
        fmp_calls["count"] += 1
        raise RuntimeError("FMP call blocked during verification")

    with patch(
        "services.wealth_adviser_llm_client.requests.post",
        side_effect=_block_llm,
    ), patch(
        "services.fmp_client.FMPClient.quote",
        side_effect=_block_fmp,
    ):
        view1 = intelligence.build_view(portfolio_before, enrich_nabi=True)
        dashboard1 = build_portfolio_intelligence_dashboard(view1)
        price_fetches_1 = price_service.fetch_count

        view2 = intelligence.build_view(portfolio_before, enrich_nabi=True)
        dashboard2 = build_portfolio_intelligence_dashboard(view2)
        price_fetches_2 = price_service.fetch_count

    results["persistence"] = {
        "portfolio_id_stable": view1.portfolio_id == view2.portfolio_id,
        "position_count_stable": view1.total_position_count == view2.total_position_count,
        "reload_market_value": view2.priced_total_market_value,
    }
    results["provider_safety"] = {
        "llm_calls": llm_calls["count"],
        "fmp_calls": fmp_calls["count"],
        "price_provider": view2.price_provider,
        "candidate_price_fetches_first_build": price_fetches_1,
        "candidate_price_fetches_after_reload": price_fetches_2,
        "unique_price_symbols_fetched": view2.unique_price_symbols_fetched,
    }

    chart_errors = []
    try:
        build_position_allocation_chart(list(dashboard2.enriched_positions))
        build_allocation_bar_chart(dashboard2.sector_allocation, title="Sektör")
        build_allocation_bar_chart(dashboard2.participation_allocation, title="Katılım")
        build_allocation_bar_chart(dashboard2.research_coverage_allocation, title="Araştırma")
        build_pl_by_position_chart(list(dashboard2.enriched_positions))
    except Exception as exc:
        chart_errors.append(str(exc))
    results["charts"] = {"ok": not chart_errors, "errors": chart_errors}

    from repositories.candidate_repository import CandidateRepository

    repo = CandidateRepository(client)
    candidates = repo.get_all(order_by="nabi_score", descending=True)[:50]
    filter_checks = {}
    for label in COMPANY_REPORT_PARTICIPATION_FILTERS:
        filtered = filter_candidates_by_participation(candidates, label)
        filter_checks[label] = len(filtered)
    results["company_report_participation_filter"] = filter_checks

    held_symbol = None
    for row in dashboard2.enriched_positions:
        if not row.valuation.is_cash:
            held_symbol = row.valuation.symbol
            break
    exposure = build_wealth_exposure_context(view2, held_symbol or "AAPL")
    portfolio_ctx = build_symbol_portfolio_context(client, user_id, held_symbol or "AAPL")
    results["company_report_integration"] = {
        "held_symbol": held_symbol,
        "exposure_held": exposure.held,
        "portfolio_context_held": portfolio_ctx.held if portfolio_ctx else False,
        "weight_pct": portfolio_ctx.portfolio_weight_pct if portfolio_ctx else None,
    }

    results["attention_items"] = [
        {"code": item.code, "severity": item.severity, "title": item.title}
        for item in dashboard2.attention_items
    ]

    context = build_context_from_view(view2)
    context_dict = context.to_dict()
    assert_portfolio_research_context_safe(context_dict)
    serialized = json.dumps(context_dict)
    results["research_context"] = {
        "schema_version": context.schema_version,
        "position_count": len(context.positions),
        "secret_free": "api_key" not in serialized.lower()
        and "secret" not in serialized.lower(),
    }

    # RLS: own data readable
    own_positions = client.table("wealth_positions").select("id").eq("user_id", user_id).execute()
    results["rls_own_read"] = len(own_positions.data or [])

    # Cross-user: attempt read with fake user_id should return empty (RLS)
    fake_uid = "00000000-0000-0000-0000-000000000001"
    foreign = (
        client.table("wealth_positions")
        .select("id")
        .eq("user_id", fake_uid)
        .execute()
    )
    results["rls_cross_user_rows"] = len(foreign.data or [])

    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
