#!/usr/bin/env python3
"""Controlled OpenFIGI FIXED_INCOME Security Master ingest for SPSK.

Writes security_master only. Does not enable hybrid. Does not write SUKUK.
Does not rewrite official fund snapshots.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.fund_holdings_repository import FundHoldingsRepository
from repositories.security_master_repository import SecurityMasterRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from services.fund_holdings_service import FundHoldingsService
from services.hybrid_exposure_allocation_policy import (
    HybridPortfolioMode,
    resolve_hybrid_allocation_policy,
    resolve_hybrid_portfolio_mode,
)
from services.layer_exposure_determinacy import assess_economic_exposure_determinacy
from services.official_fund_holdings_client import OfficialFundHoldingsClient
from services.openfigi_client import OpenFigiClient
from services.openfigi_security_master_ingest import (
    ingest_openfigi_facts,
    jobs_from_official_holdings,
    plan_openfigi_ingest,
)
from services.portfolio_allocation_intelligence import AllocationDimension
from services.portfolio_allocation_policy_service import PortfolioAllocationPolicyService
from services.portfolio_economic_exposure import build_economic_exposure
from services.security_master_listing_ingest import SecurityMasterWriteGuard
from services.security_master_service import (
    production_security_master,
    summarize_holding_coverage,
)
from services.spsk_underlying_resolution import dry_run_spsk_holdings
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.wealth_goal_planning import planning_conversion
from services.wealth_new_money_allocation import allocate_new_money
from services.wealth_planning_fx import load_planning_fx_schedule

_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})
CINS_IDS = ("Y57542AA3", "Y54788AB3", "Y5749LAB7", "Y57542AB1")
SHADOW_TARGETS = (
    ("equity", 75.0),
    ("fixed_income", 5.0),
    ("sukuk", 10.0),
    ("real_estate", 5.0),
    ("cash", 5.0),
    ("commodity", 0.0),
    ("other", 0.0),
)


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


def _invariants(client: Any, queue_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "queue": {
            "total": len(queue_rows),
            "status": dict(Counter(str(row.get("status") or "") for row in queue_rows)),
            "participation": dict(
                Counter(str(row.get("participation_status") or "") for row in queue_rows)
            ),
            "research_allowed": dict(
                Counter(str(row.get("research_allowed")) for row in queue_rows)
            ),
        },
        "security_master": _count(client, "security_master"),
        "fund_holdings": _count(client, "fund_holdings"),
        "fund_holdings_snapshots": _count(client, "fund_holdings_snapshots"),
        "investment_candidates": _count(client, "investment_candidates"),
        "wealth_portfolios": _count(client, "wealth_portfolios"),
        "wealth_adviser_goals": _count(client, "wealth_adviser_goals"),
        "wealth_transactions": _count(client, "wealth_transactions"),
    }


def _portfolio_bundle(raw: Any, client: Any, user_id: str) -> dict[str, Any]:
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
    total = float(exposure.observable_total_market_value or 0.0)
    contrib = {}
    if unknown is not None:
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
            contrib[symbol] = (
                round(float(inst.observable_market_value or 0.0) * unk_w / 100.0 / total * 100.0, 4)
                if total
                else 0.0
            )
    known_layers = {
        row.bucket_id: float(row.observable_weight_pct or 0.0)
        for row in exposure.buckets
        if row.bucket_id != "unknown"
    }
    spsk = next((row for row in exposure.instruments if str(row.symbol).upper() == "SPSK"), None)
    spsk_layers = {}
    if spsk is not None:
        spsk_layers = {
            item.exposure_bucket: float(item.weight_pct or 0.0) for item in spsk.economic_exposures
        }
    return {
        "wealth": wealth,
        "portfolio": portfolio,
        "view": view,
        "snapshots": snapshots,
        "master": master,
        "exposure": exposure,
        "assets": wealth.list_assets(),
        "positions": wealth.list_positions(),
        "summary": {
            "id": portfolio.get("id"),
            "name": portfolio.get("name"),
            "mv": view.priced_total_market_value,
            "known_pct": round(100.0 - float(unknown.observable_weight_pct or 0.0), 4)
            if unknown
            else None,
            "unknown_pct": None if unknown is None else unknown.observable_weight_pct,
            "unknown_mv": None if unknown is None else unknown.observable_market_value,
            "contributors": contrib,
            "layers": known_layers,
            "spsk_layers": spsk_layers,
        },
    }


def _spsk_snapshot(client: Any, master: Any) -> dict[str, Any]:
    from services.fund_intelligence_contract import FundHoldingRow

    snap = FundHoldingsRepository(client).get_latest_snapshot("SPSK")
    holdings = FundHoldingsRepository(client).list_holdings(str(snap["id"])) if snap else []
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
    coverage = summarize_holding_coverage(views, security_master=master) if views else {}
    return {
        "source": None if snap is None else snap.get("source"),
        "as_of": None if snap is None else snap.get("as_of"),
        "rows": len(holdings),
        "raw_weight": round(sum(float(row.get("weight_pct") or 0.0) for row in holdings), 4),
        "coverage": coverage,
        "snapshot_id": None if snap is None else snap.get("id"),
    }


def _new_money(bundle: dict[str, Any], *, hybrid: bool) -> dict[str, Any]:
    wealth = bundle["wealth"]
    portfolio = bundle["portfolio"]
    view = bundle["view"]
    policy = PortfolioAllocationPolicyService(wealth.client, wealth.user_id).get_policy(
        str(portfolio.get("id") or "")
    )
    candidates = CandidateRepository(wealth.client).get_all(limit=5000) or []
    fx = load_planning_fx_schedule(wealth, str(portfolio.get("id") or ""))
    conversion = planning_conversion(fx.usdtry_for_year(date.today().year))
    plan = allocate_new_money(
        available_amount=Decimal("100000"),
        amount_currency="TRY",
        portfolio_view=view,
        policy=policy,
        candidates=candidates,
        conversion=conversion,
        assets=bundle["assets"],
        positions=bundle["positions"],
        fund_snapshots=bundle["snapshots"],
        security_master=bundle["master"],
        enable_hybrid_exposure_allocation=True if hybrid else None,
    )
    fills = []
    from services.exposure_determinacy_diagnostics import eligible_fill_assets

    fill_assets = eligible_fill_assets(
        bundle["exposure"].instruments,
        extra_symbols=candidates,
        assets=bundle["assets"],
    )
    spsk = next((row for row in fill_assets if row.symbol == "SPSK"), None)
    return {
        "hybrid_requested": hybrid,
        "hybrid_active": plan.hybrid_allocation_active,
        "mode": plan.hybrid_portfolio_mode,
        "allocated": str(plan.total_allocated),
        "residual": str(plan.residual_cash),
        "limitations": list(plan.limitations),
        "recommendations": [
            {
                "symbol": row.symbol,
                "layer": row.layer,
                "amount": str(row.allocated_amount),
            }
            for row in plan.recommendations
        ],
        "spsk_fill_layers": None if spsk is None else list(spsk.layers),
        "eligible_fill": [row.to_dict() for row in fill_assets],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    readonly = ReadOnlyGuard(raw)
    report: dict[str, Any] = {
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "apply": args.apply,
        "writes": {"security_master": 0, "other": 0},
    }

    queue_rows = UniverseExpansionRepository(readonly).list_all()
    report["pre_write"] = _invariants(readonly, queue_rows)
    user_id = _user_id(raw)
    before = _portfolio_bundle(raw, readonly, user_id)
    report["pre_portfolio"] = before["summary"]
    report["pre_spsk"] = _spsk_snapshot(readonly, before["master"])

    official = OfficialFundHoldingsClient().fetch("SPSK")
    job_rows = jobs_from_official_holdings(official.holdings)
    client = OpenFigiClient(api_key=None)
    mapped = client.map_jobs([job for job, _name, _w in job_rows])
    by_job = {(row.job.id_type, row.job.id_value): row for row in mapped}
    mappings = []
    names = {}
    for job, name, weight in job_rows:
        names[(job.id_type, job.id_value)] = name
        mappings.append((job, by_job[(job.id_type, job.id_value)], weight))
    existing = SecurityMasterRepository(readonly).list_all()
    observed_at = datetime.now(timezone.utc).isoformat()
    plan = plan_openfigi_ingest(
        mappings,
        existing_rows=existing,
        official_names=names,
        observed_at=observed_at,
    )
    report["openfigi"] = {
        "jobs": len(job_rows),
        "requests": client.request_count,
        "match": dict(Counter(row.match_status for row in mapped)),
        "http": dict(Counter(row.http_status for row in mapped)),
    }
    report["dry_run"] = plan.to_dict()
    report["sukuk_planned"] = plan.sukuk_planned
    unresolved = [
        {
            "identifier": ident,
            "weight": next((w for job, _n, w in job_rows if job.id_value == ident), None),
        }
        for ident in CINS_IDS
    ]
    report["unresolved_cins"] = unresolved

    if plan.write_gate != "PASS" or not args.apply:
        report["production_ingest"] = {
            "performed": False,
            "write_gate": plan.write_gate,
            "reasons": list(plan.write_gate_reasons),
        }
        print(json.dumps(report, default=str))
        return 0 if plan.write_gate == "PASS" and not args.apply else 2

    writer = SecurityMasterWriteGuard(raw)
    from services.security_master_service import SecurityMasterService

    live = SecurityMasterService(
        repo=SecurityMasterRepository(writer),
        include_canonical_static=False,
    )
    first = ingest_openfigi_facts(live, plan)
    if any(str(row.get("instrument_type") or "") == "SUKUK" for row in first.rows):
        raise RuntimeError("SUKUK rows written")
    report["production_ingest"] = {
        "performed": True,
        "inserted": first.inserted,
        "updated": first.updated,
        "unchanged": first.unchanged,
        "sukuk_rows_written": 0,
    }
    report["writes"]["security_master"] = first.inserted + first.updated

    replay_plan = plan_openfigi_ingest(
        mappings,
        existing_rows=live.repo.list_all(),
        official_names=names,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    replay = ingest_openfigi_facts(live, replay_plan)
    report["idempotency"] = {
        "replay_inserted": replay.inserted,
        "replay_updated": replay.updated,
        "replay_unchanged": replay.unchanged,
        "plan": replay_plan.to_dict(),
        "duplicates": live.repo.count() - (report["pre_write"]["security_master"] or 0) - first.inserted,
    }

    after = _portfolio_bundle(raw, readonly, user_id)
    report["post_portfolio"] = after["summary"]
    report["post_spsk"] = _spsk_snapshot(readonly, after["master"])
    official_dry = dry_run_spsk_holdings(official.holdings, security_master=after["master"])
    report["official_lookthrough"] = {
        "source": official.source,
        "rows": len(official.holdings),
        "raw_weight": round(sum(item.weight_pct for item in official.holdings), 4),
        "instrument_weight": {k: round(v, 4) for k, v in official_dry.instrument_weight.items()},
    }

    unknown_pct = float(after["summary"]["unknown_pct"] or 0.0)
    known = {
        key: float(after["summary"]["layers"].get(key, 0.0) or 0.0)
        for key, _target in SHADOW_TARGETS
    }
    shadow = assess_economic_exposure_determinacy(
        targets=SHADOW_TARGETS,
        known_by_layer=known,
        unknown_pct=unknown_pct,
        tolerance_pct=2.0,
        valuation_complete=True,
        unpriced=False,
        max_unknown_portfolio_pct=1.00,
    )
    mode = resolve_hybrid_portfolio_mode(
        policy=resolve_hybrid_allocation_policy(True),
        determinacy=shadow,
        valuation_complete=True,
        unpriced=False,
        dimension=AllocationDimension.ECONOMIC_EXPOSURE.value,
    )
    report["shadow"] = {
        "unknown": shadow.unknown_pct,
        "known": shadow.known_pct,
        "candidate_mode": mode.value,
        "layers": [row.to_dict() for row in shadow.layers],
    }
    report["production_new_money"] = _new_money(after, hybrid=False)
    report["hybrid_uat"] = _new_money(after, hybrid=True)

    queue_after = UniverseExpansionRepository(readonly).list_all()
    report["post_write"] = _invariants(readonly, queue_after)
    print(json.dumps(report, default=str))
    if report["idempotency"]["replay_inserted"] or report["idempotency"]["replay_updated"]:
        return 3
    if report["sukuk_planned"] or report["production_ingest"]["sukuk_rows_written"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
