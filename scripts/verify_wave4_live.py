#!/usr/bin/env python3
"""Live verification harness for Wave 4 Full Wealth OS."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.wealth_portfolio_admin_repository import WealthPortfolioAdminRepository
from services.asset_capability_contract import capability_for_asset_class, route_report_page
from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.daily_portfolio_brief_service import build_daily_portfolio_brief
from services.fx_attribution_service import FX_ATTRIBUTION_UNAVAILABLE, build_fx_attribution_view
from services.fund_holdings_service import FundHoldingsService
from services.fund_lookthrough_engine import build_portfolio_lookthrough
from services.fx_rate_service import FxRateService
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_research_context import build_portfolio_research_context
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.total_wealth_service import compute_total_wealth_metrics
from services.wave4_monitor_context import discover_fund_symbols_for_refresh
from services.wealth_core_service import WealthCoreService
from services.wealth_timeline_service import WealthTimelineService

VERIFY_TAG = "NABI WAVE4 LIVE VERIFY"


def _count_table(client, table: str, **filters) -> int:
    query = client.table(table).select("id", count="exact")
    for key, value in filters.items():
        query = query.eq(key, value)
    response = query.execute()
    return int(response.count or len(response.data or []))


def _verify_migration(client) -> dict:
    checks: dict[str, object] = {"ok": True}
    tables = (
        "fx_rates",
        "fund_holdings_snapshots",
        "fund_holdings",
        "wealth_automation_runs",
    )
    for table in tables:
        try:
            client.table(table).select("id").limit(1).execute()
            checks[f"table_{table}"] = True
        except Exception as exc:
            checks[f"table_{table}"] = False
            checks[f"table_{table}_error"] = str(exc)
            checks["ok"] = False

    try:
        client.table("wealth_portfolio_snapshots").select("snapshot_date").limit(1).execute()
        checks["snapshot_date_column"] = True
    except Exception as exc:
        checks["snapshot_date_column"] = False
        checks["snapshot_date_column_error"] = str(exc)
        checks["ok"] = False

    try:
        client.table("wealth_assets").select("pricing_method,research_capability").limit(1).execute()
        checks["wealth_assets_metadata"] = True
    except Exception as exc:
        checks["wealth_assets_metadata"] = False
        checks["wealth_assets_metadata_error"] = str(exc)

    return checks


def _verify_snapshot_uniqueness(client) -> dict:
    rows = client.table("wealth_portfolio_snapshots").select("portfolio_id,snapshot_date").limit(5000).execute().data or []
    groups: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("portfolio_id") or ""), str(row.get("snapshot_date") or ""))
        if not key[0] or not key[1]:
            continue
        groups[key] = groups.get(key, 0) + 1
    duplicate_groups = {k: v for k, v in groups.items() if v > 1}
    return {
        "duplicate_group_count": len(duplicate_groups),
        "ok": len(duplicate_groups) == 0,
    }


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    user_id = get_current_user_id(client)
    if not user_id:
        print(json.dumps({"status": "failed", "reason": "auth_required"}, default=str))
        return 1

    failures: list[str] = []
    results: dict[str, object] = {"verify_tag": VERIFY_TAG}

    migration = _verify_migration(client)
    results["migration"] = migration
    if not migration.get("ok"):
        failures.append("migration_tables")

    uniqueness = _verify_snapshot_uniqueness(client)
    results["snapshot_uniqueness"] = uniqueness
    if not uniqueness.get("ok"):
        failures.append("snapshot_duplicates")

    wealth = WealthCoreService(client, user_id)
    portfolio = wealth.ensure_default_portfolio()
    portfolio_id = str(portfolio["id"])

    pre_state = {
        "portfolios": _count_table(client, "wealth_portfolios", user_id=user_id),
        "accounts": _count_table(client, "wealth_accounts", user_id=user_id),
        "assets": _count_table(client, "wealth_assets", user_id=user_id),
        "snapshots": _count_table(client, "wealth_portfolio_snapshots", user_id=user_id),
        "fx_rates": _count_table(client, "fx_rates"),
        "automation_runs": _count_table(client, "wealth_automation_runs"),
    }
    results["pre_state"] = pre_state

    routing = {}
    for asset_class in ("equity", "etf", "fund", "cash", "gold", "sukuk", "other"):
        routing[asset_class] = {
            "route": route_report_page(asset_class),
            "profile": capability_for_asset_class(asset_class).to_dict(),
        }
    results["asset_routing"] = routing
    if route_report_page("equity") != "company_report":
        failures.append("equity_route")
    if route_report_page("etf") != "fund_report":
        failures.append("etf_route")
    if route_report_page("cash") == "company_report":
        failures.append("cash_route")

    price_service = CandidatePriceService(client)
    with patch("services.fmp_client.FMPClient.quote", side_effect=AssertionError("FMP blocked")):
        intelligence = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
        base_view = intelligence.build_view(portfolio, enrich_nabi=False)
        dashboard = build_portfolio_intelligence_dashboard(base_view, accounts_by_id={})

    results["pi_render"] = {
        "price_lookups": price_service.fetch_count,
        "fx_supported": base_view.fx_supported,
        "foreign_currency_position_count": base_view.foreign_currency_position_count,
        "unpriced_position_count": base_view.unpriced_position_count,
    }
    if price_service.fetch_count > 0:
        results["pi_render"]["note"] = "candidate_snapshot DB lookups only"

    fx_service = FxRateService(client)
    fx_service.remote_calls = 0
    stale_pairs = []
    for row in base_view.priced_positions + base_view.foreign_currency_positions:
        quote = fx_service.convert_amount(
            amount=100.0,
            from_currency=row.valuation_currency,
            to_currency=base_view.base_currency,
        )
        if quote.stale:
            stale_pairs.append(row.symbol)
    results["fx"] = {
        "remote_calls": fx_service.remote_calls,
        "stale_symbols": stale_pairs,
    }
    if fx_service.remote_calls != 0:
        failures.append("fx_remote_on_render")

    fund_service = FundHoldingsService(client)
    lookthrough = build_portfolio_lookthrough(
        positions=[
            {
                "symbol": row.valuation.symbol,
                "asset_class": row.valuation.asset_class,
                "weight_pct": row.valuation.weight_pct,
                "market_value": row.valuation.market_value,
                "is_cash": row.valuation.is_cash,
                "participation_status": row.participation_status,
            }
            for row in dashboard.enriched_positions
        ],
        fund_service=fund_service,
        total_market_value=float(base_view.priced_total_market_value),
    )
    wealth_metrics = compute_total_wealth_metrics(
        base_view,
        participation_covered_pct=dashboard.participation_eligible_weight_pct,
        research_covered_pct=dashboard.research_coverage_weight_pct,
    )
    results["total_wealth"] = wealth_metrics.to_dict()
    results["lookthrough"] = lookthrough.to_dict()

    fx_attr = build_fx_attribution_view(
        symbol="TEST",
        native_currency="EUR",
        base_currency=base_view.base_currency,
    )
    results["fx_attribution"] = fx_attr.to_dict()
    if fx_attr.status != FX_ATTRIBUTION_UNAVAILABLE:
        failures.append("fx_attribution_should_be_unavailable")

    monitor = MonitorIntelligenceService(client, user_id)
    with patch("services.fmp_client.FMPClient.quote", side_effect=AssertionError("FMP blocked")):
        created, skipped = monitor.refresh_portfolio_events(portfolio=portfolio, dashboard=dashboard)
    brief = build_daily_portfolio_brief(portfolio=portfolio, dashboard=dashboard, monitor=monitor)
    results["monitor_wave4"] = {
        "created": created,
        "skipped": skipped,
        "wealth_event_count": brief.event_counts.get("wealth", 0),
    }

    context = build_portfolio_research_context(dashboard)
    results["portfolio_ai_context"] = {
        "schema_version": context.schema_version,
        "fx_supported": context.summary.get("fx_supported"),
        "asset_class_allocation_count": len(context.summary.get("asset_class_allocation") or []),
        "fx_attribution_status": context.summary.get("fx_attribution_status"),
    }

    admin = WealthPortfolioAdminRepository(client)
    active_portfolios = admin.list_active_portfolios_for_snapshot()
    results["multi_user_snapshot_discovery"] = {
        "active_portfolio_count": len(active_portfolios),
    }
    results["fund_symbol_discovery_count"] = len(discover_fund_symbols_for_refresh(client))

    timeline = WealthTimelineService(wealth)
    snap1 = timeline.save_snapshot_from_view(portfolio, base_view)
    snap2 = timeline.save_snapshot_from_view(portfolio, base_view)
    results["snapshot_idempotency"] = {
        "same_snapshot_id": snap1.id == snap2.id,
    }
    if snap1.id != snap2.id:
        failures.append("snapshot_idempotency")

    results["status"] = "pass" if not failures else "fail"
    results["failures"] = failures
    print(json.dumps(results, default=str, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
