#!/usr/bin/env python3
"""Read-only 8C probe: SI table, local price history, TSLA cache."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.sec_company_facts_cache import SecCompanyFactsCache
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client

SYMBOLS = ("AAPL", "AVGO", "CRM", "TSLA", "MRVL", "UPS")


def _safe_count(client, table: str) -> dict:
    try:
        rows = client.table(table).select("id", count="exact").limit(1).execute()
        return {"exists": True, "count": getattr(rows, "count", None)}
    except Exception as exc:
        return {"exists": False, "error": str(exc)[:180]}


def main() -> int:
    apply_local_secrets_to_env()
    client = create_admin_supabase_client()
    report: dict = {"tables": {}, "scan_results": {}, "wealth_snapshots": {}, "tsla_cache": {}}
    for table in (
        "security_intelligence_snapshots",
        "scan_results",
        "investment_candidates",
        "wealth_portfolio_snapshots",
        "wealth_positions",
        "wealth_transactions",
        "participation_assessment_snapshots",
    ):
        report["tables"][table] = _safe_count(client, table)

    for symbol in SYMBOLS:
        try:
            rows = (
                client.table("scan_results")
                .select("created_at,candidate_snapshot")
                .eq("symbol", symbol)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            report["scan_results"][symbol] = {"error": str(exc)[:160]}
            continue
        prices = []
        for row in rows:
            snap = row.get("candidate_snapshot") or {}
            prices.append(
                {
                    "created_at": row.get("created_at"),
                    "has_price": "current_price" in snap or "price" in snap,
                    "keys": sorted(list(snap.keys()))[:12] if isinstance(snap, dict) else [],
                }
            )
        report["scan_results"][symbol] = {"rows": len(rows), "samples": prices[:5]}

    try:
        snaps = (
            client.table("wealth_portfolio_snapshots")
            .select("captured_at,valuation_payload")
            .order("captured_at", desc=True)
            .limit(50)
            .execute()
            .data
            or []
        )
        by_symbol: dict[str, list] = {s: [] for s in SYMBOLS}
        for row in snaps:
            payload = row.get("valuation_payload") or {}
            for pos in payload.get("priced_positions") or []:
                sym = str(pos.get("symbol") or "").strip().upper()
                if sym in by_symbol and pos.get("price") is not None:
                    by_symbol[sym].append(
                        {"captured_at": row.get("captured_at"), "price": pos.get("price")}
                    )
        report["wealth_snapshots"] = {
            "rows": len(snaps),
            "by_symbol": {k: v[:8] for k, v in by_symbol.items()},
            "counts": {k: len(v) for k, v in by_symbol.items()},
        }
    except Exception as exc:
        report["wealth_snapshots"] = {"error": str(exc)[:200]}

    cache = SecCompanyFactsCache()
    for symbol in SYMBOLS:
        ev = cache.get_latest(symbol=symbol)
        report["tsla_cache" if symbol == "TSLA" else "cache"] = report.get("cache") or {}
        report.setdefault("cache", {})[symbol] = ev is not None
    report["tsla_cache"] = {
        "present": cache.get_latest(symbol="TSLA") is not None,
        "manifest_symbols": sorted((cache._read_manifest().get("latest_by_symbol") or {}).keys())[:40],
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
