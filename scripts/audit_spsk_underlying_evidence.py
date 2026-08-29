#!/usr/bin/env python3
"""Read-only SPSK identifier / Security Master evidence audit.

Default: zero writes. Official issuer CSV is the only optional network read.
Does not enable hybrid. Does not infer SPSK = sukuk.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.fund_holdings_repository import FundHoldingsRepository
from repositories.security_master_repository import SecurityMasterRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from services.fund_holdings_service import FundHoldingsService
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.official_fund_holdings_client import OfficialFundHoldingsClient
from services.portfolio_economic_exposure import build_economic_exposure
from services.security_master_service import (
    production_security_master,
    summarize_holding_coverage,
)
from services.spsk_underlying_resolution import dry_run_spsk_holdings
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client

_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


class ReadOnlyGuard:
    def __init__(self, client: Any) -> None:
        self._client = client

    def table(self, name: str):
        return _ReadOnlyTable(self._client.table(name), name)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _ReadOnlyTable:
    def __init__(self, inner: Any, table_name: str) -> None:
        self._inner = inner
        self._table_name = table_name

    def __getattr__(self, name: str):
        if name in _WRITE_METHODS:
            def _blocked(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError(f"blocked write on {self._table_name}.{name}")

            return _blocked
        return getattr(self._inner, name)


def _count(client: Any, table: str) -> int | None:
    try:
        response = client.table(table).select("id", count="exact").limit(1).execute()
        return int(getattr(response, "count", None) or 0)
    except Exception:
        return None


def _user_id(client: Any) -> str:
    user = getattr(getattr(client, "auth", None), "get_user", lambda: None)()
    uid = getattr(getattr(user, "user", None), "id", None)
    if uid:
        return str(uid)
    rows = (
        client.table("wealth_portfolios")
        .select("user_id")
        .eq("is_default", True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise RuntimeError("no default portfolio user")
    return str(rows[0]["user_id"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-official", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    client = ReadOnlyGuard(raw)
    report: dict[str, Any] = {
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "writes": 0,
        "fmp_calls": 0,
        "llm_calls": 0,
        "official_issuer_calls": 0,
    }

    queue_rows = UniverseExpansionRepository(client).list_all()
    report["queue"] = {
        "total": len(queue_rows),
        "status": dict(Counter(str(row.get("status") or "") for row in queue_rows)),
        "participation": dict(
            Counter(str(row.get("participation_status") or "") for row in queue_rows)
        ),
        "research_allowed": dict(
            Counter(str(row.get("research_allowed")) for row in queue_rows)
        ),
    }
    report["invariants"] = {
        "security_master": _count(client, "security_master"),
        "fund_holdings": _count(client, "fund_holdings"),
        "fund_holdings_snapshots": _count(client, "fund_holdings_snapshots"),
        "investment_candidates": _count(client, "investment_candidates"),
        "wealth_portfolios": _count(client, "wealth_portfolios"),
        "wealth_adviser_goals": _count(client, "wealth_adviser_goals"),
        "wealth_transactions": _count(client, "wealth_transactions"),
    }

    user_id = _user_id(raw)
    from services.candidate_price_service import CandidatePriceService
    from services.portfolio_intelligence_service import PortfolioIntelligenceService
    from services.wealth_core_service import WealthCoreService

    wealth = WealthCoreService(client, user_id)
    with patch.object(
        wealth,
        "ensure_default_portfolio",
        side_effect=RuntimeError("ensure_default_portfolio blocked"),
    ):
        portfolio = WealthPortfolioRepository(client).get_default_for_user(user_id)
        if portfolio is None:
            raise RuntimeError("default portfolio missing")
        intel = PortfolioIntelligenceService(wealth, CandidatePriceService(client))
        view = intel.build_view(portfolio, enrich_nabi=False)
        holdings_svc = FundHoldingsService(client)
        snapshots = {
            symbol: snap
            for symbol in ("SPUS", "SPSK", "SPRE", "SPWO")
            if (snap := holdings_svc.get_snapshot(symbol)) is not None
        }
        master = production_security_master(client)
        exposure = build_economic_exposure(
            view,
            fund_snapshots=snapshots,
            assets=wealth.list_assets(),
            positions=wealth.list_positions(),
            security_master=master,
        )
    unknown = next((row for row in exposure.buckets if row.bucket_id == "unknown"), None)
    contrib = {}
    if unknown is not None:
        total = float(exposure.observable_total_market_value or 0.0)
        for symbol in unknown.contributing_symbols:
            inst = next(
                (row for row in exposure.instruments if str(row.symbol).upper() == symbol),
                None,
            )
            if inst is None:
                continue
            unk_w = sum(
                float(item.weight_pct or 0.0)
                for item in inst.economic_exposures
                if item.exposure_bucket == "unknown"
            )
            contrib[symbol] = round(float(inst.observable_market_value or 0.0) * unk_w / 100.0 / total * 100.0, 4) if total else 0.0
    report["portfolio"] = {
        "id": portfolio.get("id"),
        "name": portfolio.get("name"),
        "mv": view.priced_total_market_value,
        "unknown_pct": None if unknown is None else unknown.observable_weight_pct,
        "unknown_mv": None if unknown is None else unknown.observable_market_value,
        "contributors": contrib,
        "known_pct": round(100.0 - float(unknown.observable_weight_pct or 0.0), 4) if unknown else None,
    }

    snap = FundHoldingsRepository(client).get_latest_snapshot("SPSK")
    holdings = FundHoldingsRepository(client).list_holdings(str(snap["id"])) if snap else []
    report["spsk_snapshot"] = {
        "source": None if snap is None else snap.get("source"),
        "as_of": None if snap is None else snap.get("as_of"),
        "rows": len(holdings),
        "raw_weight": round(sum(float(row.get("weight_pct") or 0.0) for row in holdings), 4),
        "coverage_pct": None if snap is None else snap.get("coverage_pct"),
    }
    if holdings:
        from services.fund_intelligence_contract import FundHoldingRow

        views = [
            FundHoldingRow(
                underlying_symbol=row.get("underlying_symbol"),
                underlying_name=row.get("underlying_name"),
                weight_pct=row.get("weight_pct"),
                asset_type=row.get("asset_type"),
                participation_status=row.get("participation_status"),
                research_status=row.get("research_status"),
            )
            for row in holdings
        ]
        report["spsk_lookthrough"] = summarize_holding_coverage(
            views, security_master=master
        )

    crm_queue = next(
        (row for row in queue_rows if str(row.get("symbol") or "").upper() == "CRM"),
        None,
    )
    from config.participation_catalog import configured_participation_for_symbol

    report["crm_audit"] = {
        "catalog": configured_participation_for_symbol("CRM"),
        "spsk_catalog": configured_participation_for_symbol("SPSK"),
        "spus_catalog": configured_participation_for_symbol("SPUS"),
        "queue_participation": None if crm_queue is None else crm_queue.get("participation_status"),
        "queue_research_allowed": None if crm_queue is None else crm_queue.get("research_allowed"),
    }

    if args.fetch_official:
        official = OfficialFundHoldingsClient().fetch("SPSK")
        report["official_issuer_calls"] = 1
        dry = dry_run_spsk_holdings(official.holdings, security_master=master)
        payload = dry.to_dict()
        payload.pop("rows", None)
        report["official"] = {
            "as_of": official.as_of.isoformat(),
            "source": official.source,
            "rows": len(official.holdings),
            "raw_columns": list(official.raw_columns),
            "weight_sum": round(sum(item.weight_pct for item in official.holdings), 4),
            "dry_run": payload,
            "sample_unverified": [
                {
                    "ticker": row.stock_ticker,
                    "cusip": row.cusip_raw,
                    "name": row.security_name,
                    "weight": row.weight_pct,
                    "ticker_u": row.ticker_assessment.usability,
                    "cusip_u": row.cusip_assessment.usability,
                }
                for row in dry.rows[:8]
            ],
        }
        spsk_port = float((contrib.get("SPSK") or 0.0))
        classified = sum(
            w
            for key, w in dry.instrument_weight.items()
            if key != "UNKNOWN"
        )
        raw = sum(dry.instrument_weight.values()) or 1.0
        classified_frac = classified / raw
        unknown_spsk_after = spsk_port * (1.0 - classified_frac)
        other_unknown = float(report["portfolio"]["unknown_pct"] or 0.0) - spsk_port
        report["projected"] = {
            "spsk_classified_weight_pct_of_fund": round(classified, 4),
            "spsk_unknown_weight_pct_of_fund": round(dry.instrument_weight.get("UNKNOWN", 0.0), 4),
            "portfolio_unknown_before": report["portfolio"]["unknown_pct"],
            "portfolio_unknown_after": round(other_unknown + unknown_spsk_after, 4),
        }

    print(json.dumps(report, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
