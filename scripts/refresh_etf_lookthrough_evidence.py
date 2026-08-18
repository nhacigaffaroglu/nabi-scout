#!/usr/bin/env python3
"""Controlled ETF look-through evidence refresh for SPUS/SPSK/SPRE/SPWO only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.fmp_client import FMPClient, FMPError
from services.fund_holdings_refresh_service import (
    LOOKTHROUGH_ONBOARDING_SYMBOLS,
    FundHoldingsRefreshService,
)
from services.fund_holdings_service import FundHoldingsService
from services.portfolio_economic_exposure import classify_instrument_exposure
from services.portfolio_intelligence_contract import PositionValuationRow
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client


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


def _exposure_breakdown(symbol: str, snapshot) -> dict:
    view = classify_instrument_exposure(_etf_row(symbol), fund_snapshots={symbol: snapshot})
    return {
        "complete": view.evidence_complete,
        "exposures": [
            {"bucket": row.exposure_bucket, "weight_pct": row.weight_pct}
            for row in view.economic_exposures
        ],
        "unknown_weight": sum(
            float(row.weight_pct)
            for row in view.economic_exposures
            if row.exposure_bucket == "unknown"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled ETF look-through refresh")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=list(LOOKTHROUGH_ONBOARDING_SYMBOLS),
        help="Subset of SPUS SPSK SPRE SPWO",
    )
    args = parser.parse_args()

    requested = []
    skipped = []
    allow = set(LOOKTHROUGH_ONBOARDING_SYMBOLS)
    for raw in args.symbols:
        symbol = str(raw or "").strip().upper()
        if symbol in allow and symbol not in requested:
            requested.append(symbol)
        elif symbol:
            skipped.append(symbol)
    if not requested:
        requested = list(LOOKTHROUGH_ONBOARDING_SYMBOLS)

    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    try:
        fmp = FMPClient.from_env()
    except FMPError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc.error_class or exc)}, default=str))
        return 1

    refresh = FundHoldingsRefreshService(client, fmp_client=fmp)
    results = refresh.refresh_requested_symbols(requested)
    reader = FundHoldingsService(client)
    for row in results:
        snapshot = reader.get_snapshot(str(row["symbol"])) if row.get("persisted") else None
        if snapshot is not None:
            row["exposure"] = _exposure_breakdown(str(row["symbol"]), snapshot)
        else:
            row["exposure"] = {
                "complete": False,
                "exposures": [{"bucket": "unknown", "weight_pct": 100.0}],
                "unknown_weight": 100.0,
            }

    payload = {
        "status": "completed",
        "symbols": requested,
        "skipped_outside_allowlist": skipped,
        "provider_calls": refresh.provider_calls,
        "sec_calls": 0,
        "llm_calls": 0,
        "results": results,
    }
    print(json.dumps(payload, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
