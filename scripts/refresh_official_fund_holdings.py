#!/usr/bin/env python3
"""Controlled official SP Funds holdings ingest.

Writes only fund_holdings / fund_holdings_snapshots. No FMP, no queue writes,
no Security Master writes, no Participation/New Money/Adviser.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.fund_holdings_repository import FundHoldingsRepository
from repositories.security_master_repository import SecurityMasterRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.fund_holdings_service import FundHoldingsService
from services.official_fund_holdings_client import (
    SUPPORTED_OFFICIAL_FUNDS,
    OfficialFundHoldingsClient,
)
from services.official_fund_holdings_ingest import (
    OfficialFundHoldingsIngestService,
    OfficialHoldingsWriteGuard,
    audit_official_file,
)
from services.portfolio_economic_exposure import classify_instrument_exposure
from services.portfolio_intelligence_contract import PositionValuationRow
from services.security_master_service import SecurityMasterService


def _etf_row(symbol: str) -> PositionValuationRow:
    return PositionValuationRow(
        position_id=f"p-{symbol}",
        account_id="a1",
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class="etf",
        account_name="Broker",
        quantity=1,
        average_cost=1,
        valuation_currency="USD",
        price=1,
        price_available=True,
        market_value=1,
        cost_basis=1,
        unrealized_pl=0,
        weight_pct=None,
        is_cash=False,
        included_in_base_totals=True,
    )


def _queue_snapshot(client) -> dict[str, Any]:
    rows = UniverseExpansionRepository(client).list_all()
    return {
        "total": len(rows),
        "status": dict(Counter(str(row.get("status") or "") for row in rows)),
        "participation": dict(Counter(str(row.get("participation_status") or "") for row in rows)),
        "research_allowed": dict(Counter(str(row.get("research_allowed")) for row in rows)),
    }


def _count(client, table: str) -> int | None:
    try:
        response = client.table(table).select("id", count="exact").limit(1).execute()
        return int(getattr(response, "count", None) or 0)
    except Exception:
        return None


def _invariants(client, queue: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue": queue,
        "security_master": _count(client, "security_master"),
        "investment_candidates": _count(client, "investment_candidates"),
        "wealth_portfolios": _count(client, "wealth_portfolios"),
        "wealth_adviser_goals": _count(client, "wealth_adviser_goals"),
        "wealth_transactions": _count(client, "wealth_transactions"),
    }


def _memory_master(rows: list[dict[str, Any]]) -> SecurityMasterService:
    repo = SecurityMasterRepository()
    for row in rows:
        key = (
            str(row.get("identifier") or "").strip().upper(),
            str(row.get("identifier_type") or "").strip().upper(),
            str(row.get("source") or "").strip(),
        )
        repo._memory[key] = dict(row)
    return SecurityMasterService(repo=repo, include_canonical_static=True)


def _lookthrough_report(snapshot, master: SecurityMasterService) -> dict[str, Any]:
    view = classify_instrument_exposure(
        _etf_row(snapshot.fund_symbol),
        fund_snapshots={snapshot.fund_symbol: snapshot},
        security_master=master,
    )
    buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
    unknown = float(buckets.get("unknown") or 0.0)
    classified = round(sum(weight for key, weight in buckets.items() if key != "unknown"), 4)
    limitations = sorted({item for row in view.economic_exposures for item in row.limitations})
    return {
        "as_of": snapshot.as_of,
        "source": snapshot.source,
        "rows": len(snapshot.holdings),
        "weight": round(sum(float(row.weight_pct or 0.0) for row in snapshot.holdings), 4),
        "coverage_pct": snapshot.coverage_pct,
        "complete": view.evidence_complete,
        "normalization": "ISSUER_WEIGHT_ROUNDING_NORMALIZED" in limitations,
        "overflow": "MATERIAL_ISSUER_WEIGHT_OVERFLOW" in limitations,
        "classified": classified,
        "unknown": unknown,
        "buckets": buckets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Official SP Funds holdings ingest")
    parser.add_argument("--phase", choices=("dry-run", "ingest"), default="dry-run")
    args = parser.parse_args()

    from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    client = OfficialHoldingsWriteGuard(raw)
    queue_before = _queue_snapshot(client)
    before = _invariants(client, queue_before)
    sm_rows = SecurityMasterRepository(client).list_all()
    master = _memory_master(sm_rows)

    client_http = OfficialFundHoldingsClient()
    files = {}
    dry = {}
    blocked = []
    for symbol in SUPPORTED_OFFICIAL_FUNDS:
        fetched = client_http.fetch(symbol)
        files[symbol] = fetched
        report = audit_official_file(fetched, security_master=master)
        dry[symbol] = report.to_dict()
        if report.blocked_reason:
            blocked.append(symbol)

    payload: dict[str, Any] = {
        "phase": args.phase,
        "nasdaq_calls": 0,
        "sec_calls": 0,
        "fmp_calls": 0,
        "llm_calls": 0,
        "official_http_calls": len(SUPPORTED_OFFICIAL_FUNDS),
        "invariants_before": before,
        "dry_run": dry,
        "blocked_funds": blocked,
        "universe_discovery": False,
        "participation_run": False,
        "new_money_run": False,
        "adviser_run": False,
    }
    if blocked or args.phase == "dry-run":
        payload["ingest"] = None
        print(json.dumps(payload, default=str))
        return 2 if blocked else 0

    service = OfficialFundHoldingsIngestService(FundHoldingsRepository(client))
    first = {}
    second = {}
    for symbol, fetched in files.items():
        first[symbol] = service.persist(fetched, security_master=master).to_dict()
        second[symbol] = service.persist(fetched, security_master=master).to_dict()

    reader = FundHoldingsService(client)
    readback = {}
    exposure = {}
    for symbol in SUPPORTED_OFFICIAL_FUNDS:
        snapshot = reader.get_snapshot(symbol)
        if snapshot is None:
            readback[symbol] = None
            exposure[symbol] = None
            continue
        readback[symbol] = _lookthrough_report(snapshot, master)
        exposure[symbol] = {
            "classified": readback[symbol]["classified"],
            "unknown": readback[symbol]["unknown"],
            "buckets": readback[symbol]["buckets"],
        }

    queue_after = _queue_snapshot(client)
    payload["ingest"] = {"first": first, "second": second}
    payload["readback"] = readback
    payload["economic_exposure"] = exposure
    payload["invariants_after"] = _invariants(client, queue_after)
    print(json.dumps(payload, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
