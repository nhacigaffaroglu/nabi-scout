#!/usr/bin/env python3
"""Controlled Security Master listing-fact ingest.

Production write target is security_master only. Does not enqueue symbols,
run Participation, fetch fund holdings, or call FMP/LLM.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.security_master_repository import SecurityMasterRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.free_universe_client import FreeUniverseClient
from services.fund_holdings_service import FundHoldingsService
from services.security_master_contract import (
    INSTRUMENT_TYPES,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
)
from services.security_master_listing_ingest import (
    SecurityMasterWriteGuard,
    ingest_merged_us_listing_facts,
    planned_listing_source_path,
)
from services.security_master_service import SecurityMasterService, summarize_holding_coverage
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.universe_discovery_service import fetch_us_equity_listing_feeds

MIGRATION = ROOT / "database" / "migration_security_master.sql"
REQUIRED_COLUMNS = (
    "id",
    "identifier",
    "identifier_type",
    "instrument_type",
    "source",
    "observed_at",
    "symbol",
    "exchange",
    "issuer_name",
    "source_reference",
    "metadata",
    "created_at",
    "updated_at",
)
FUND_SYMBOLS = ("SPUS", "SPSK", "SPRE", "SPWO")
CONFLICTING_NAME_HINTS = (
    "security_master",
    "security_facts",
    "instrument_master",
    "instrument_facts",
)


def _service_role_key() -> str:
    from services.supabase_admin_client import _resolve_service_role_key

    return _resolve_service_role_key()


def _supabase_url() -> str:
    from services.supabase_admin_client import _resolve_supabase_url

    return _resolve_supabase_url()


def _rest_table_names(url: str, key: str) -> list[str]:
    import requests

    response = requests.get(
        f"{url.rstrip('/')}/rest/v1/",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/openapi+json",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    paths = payload.get("paths") or {}
    names = []
    for path in paths:
        text = str(path or "").strip("/")
        if text and "/" not in text and not text.startswith("rpc"):
            names.append(text)
    return sorted(set(names))


def _table_probe(client: Any, table: str) -> dict[str, Any]:
    try:
        response = (
            client.table(table)
            .select("*", count="exact")
            .limit(1)
            .execute()
        )
        rows = response.data or []
        columns = sorted(rows[0].keys()) if rows else []
        return {
            "exists": True,
            "error": None,
            "count": int(getattr(response, "count", None) or 0),
            "sample_columns": columns,
        }
    except Exception as exc:
        message = str(exc)
        missing = "PGRST205" in message or "does not exist" in message.lower() or "42P01" in message
        if missing:
            return {"exists": False, "error": "missing", "count": 0, "sample_columns": []}
        return {"exists": None, "error": message[:300], "count": 0, "sample_columns": []}


def _queue_snapshot(client: Any) -> dict[str, Any]:
    repo = UniverseExpansionRepository(client)
    rows = repo.list_all()
    status = Counter(str(row.get("status") or "") for row in rows)
    participation = Counter(str(row.get("participation_status") or "") for row in rows)
    research = Counter(str(row.get("research_allowed")) for row in rows)
    sources = Counter(str(row.get("source_universe") or "") for row in rows)
    return {
        "total": len(rows),
        "status": dict(status),
        "participation": dict(participation),
        "research_allowed": dict(research),
        "source_universe": dict(sources),
        "symbols": sorted(str(row.get("symbol") or "") for row in rows),
        "rows": rows,
    }


def _count_table(client: Any, table: str) -> Optional[int]:
    try:
        response = client.table(table).select("id", count="exact").limit(1).execute()
        return int(getattr(response, "count", None) or 0)
    except Exception:
        return None


def _invariants(client: Any, queue: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue_total": queue["total"],
        "queue_status": queue["status"],
        "participation": queue["participation"],
        "research_allowed": queue["research_allowed"],
        "investment_candidates": _count_table(client, "investment_candidates"),
        "wealth_portfolios": _count_table(client, "wealth_portfolios"),
        "wealth_adviser_goals": _count_table(client, "wealth_adviser_goals"),
        "wealth_transactions": _count_table(client, "wealth_transactions"),
        "fund_holdings": _count_table(client, "fund_holdings"),
        "fund_holdings_snapshots": _count_table(client, "fund_holdings_snapshots"),
        "universe_expansion_runs": _count_table(client, "universe_expansion_runs"),
    }


def _resolve_db_url() -> str:
    from services.supabase_admin_client import load_local_secrets_toml

    secrets = load_local_secrets_toml()
    supabase = secrets.get("supabase") if isinstance(secrets.get("supabase"), dict) else {}
    candidates = (
        os.environ.get("SUPABASE_DB_URL"),
        os.environ.get("DATABASE_URL"),
        os.environ.get("SUPABASE_DATABASE_URL"),
        supabase.get("db_url"),
        supabase.get("database_url"),
        supabase.get("postgres_url"),
        supabase.get("connection_string"),
    )
    for item in candidates:
        text = str(item or "").strip()
        if text:
            return text
    return ""


def apply_security_master_migration() -> dict[str, Any]:
    db_url = _resolve_db_url()
    if not db_url:
        return {
            "applied": False,
            "reason": "no DATABASE_URL/SUPABASE_DB_URL in env or secrets",
        }
    sql = MIGRATION.read_text(encoding="utf-8")
    try:
        import psycopg

        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.execute(sql)
        return {"applied": True, "driver": "psycopg"}
    except ImportError:
        pass
    try:
        import psycopg2

        conn = psycopg2.connect(db_url)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql)
        finally:
            conn.close()
        return {"applied": True, "driver": "psycopg2"}
    except ImportError:
        return {"applied": False, "reason": "psycopg/psycopg2 not installed and no other DDL path"}


def _schema_from_openapi(url: str, key: str) -> dict[str, Any]:
    import requests

    response = requests.get(
        f"{url.rstrip('/')}/rest/v1/",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/openapi+json",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    schema = (
        ((payload.get("definitions") or {}).get("security_master"))
        or ((payload.get("components") or {}).get("schemas") or {}).get("security_master")
        or {}
    )
    properties = schema.get("properties") or {}
    return {
        "columns": sorted(properties.keys()),
        "required": schema.get("required") or [],
    }


def _fact_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    types = Counter(str(row.get("instrument_type") or "") for row in rows)
    sources = Counter(str(row.get("source") or "") for row in rows)
    exchanges = Counter(str(row.get("exchange") or "") for row in rows)
    identifier_types = Counter(str(row.get("identifier_type") or "") for row in rows)
    identity_counts = Counter(
        (row.get("identifier"), row.get("identifier_type"), row.get("source"))
        for row in rows
    )
    duplicates = [
        {"identifier": key[0], "identifier_type": key[1], "source": key[2], "count": count}
        for key, count in identity_counts.items()
        if count > 1
    ]
    for instrument in INSTRUMENT_TYPES:
        types.setdefault(instrument, 0)
    return {
        "total": len(rows),
        "by_instrument_type": dict(types),
        "by_source": dict(sources),
        "by_exchange": dict(exchanges),
        "identifier_types": dict(identifier_types),
        "duplicates": duplicates,
    }


def _conflicts(master: SecurityMasterService, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("identifier") or ""), str(row.get("identifier_type") or ""))].append(row)
    found = []
    for (identifier, identifier_type), _group in grouped.items():
        resolution = master.resolve_security(identifier, identifier_type=identifier_type)
        if resolution.status == RESOLUTION_CONFLICT:
            found.append(
                {
                    "identifier": identifier,
                    "identifier_type": identifier_type,
                    "limitation": resolution.limitation,
                }
            )
    return found


def _sample(rows: list[dict[str, Any]], instrument: str, limit: int = 5) -> list[dict[str, Any]]:
    selected = [row for row in rows if str(row.get("instrument_type") or "") == instrument]
    return [
        {
            "identifier": row.get("identifier"),
            "identifier_type": row.get("identifier_type"),
            "instrument_type": row.get("instrument_type"),
            "source": row.get("source"),
            "observed_at": row.get("observed_at"),
            "symbol": row.get("symbol"),
            "exchange": row.get("exchange"),
            "issuer_name": row.get("issuer_name"),
            "source_reference": row.get("source_reference"),
            "metadata": row.get("metadata"),
        }
        for row in selected[:limit]
    ]


def _queue_cross_check(master: SecurityMasterService, queue_rows: list[dict[str, Any]]) -> dict[str, Any]:
    persisted = {
        (str(row.get("identifier") or ""), str(row.get("identifier_type") or ""))
        for row in master.repo.list_all()
    }
    result = {
        "queue_total": len(queue_rows),
        "with_fact": 0,
        "resolved": 0,
        "resolved_equity": 0,
        "unresolved": 0,
        "conflicts": 0,
        "by_source": {},
    }
    by_source: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "with_fact": 0, "resolved": 0, "resolved_equity": 0, "unresolved": 0, "conflicts": 0}
    )
    for row in queue_rows:
        symbol = str(row.get("symbol") or "")
        source = str(row.get("source_universe") or "")
        bucket = by_source[source]
        bucket["total"] += 1
        has_fact = (symbol, "TICKER") in persisted
        if has_fact:
            result["with_fact"] += 1
            bucket["with_fact"] += 1
        resolution = master.resolve_security(symbol)
        if resolution.status == RESOLUTION_CONFLICT:
            result["conflicts"] += 1
            bucket["conflicts"] += 1
        elif resolution.status == RESOLUTION_RESOLVED:
            result["resolved"] += 1
            bucket["resolved"] += 1
            if resolution.instrument_type == "EQUITY":
                result["resolved_equity"] += 1
                bucket["resolved_equity"] += 1
        else:
            result["unresolved"] += 1
            bucket["unresolved"] += 1
    result["by_source"] = dict(by_source)
    return result


def _fund_coverage(client: Any, master: SecurityMasterService) -> dict[str, Any]:
    reader = FundHoldingsService(client)
    coverage = {}
    for symbol in FUND_SYMBOLS:
        snapshot = reader.get_snapshot(symbol)
        if snapshot is None:
            coverage[symbol] = {
                "holding_count_available": 0,
                "weight_available": False,
                "available": False,
            }
            continue
        summary = summarize_holding_coverage(snapshot.holdings, security_master=master)
        coverage[symbol] = {
            "available": True,
            "holding_count_available": summary["holding_count"],
            "weight_available": True,
            "as_of": snapshot.as_of,
            "source": snapshot.source,
            "coverage_pct": snapshot.coverage_pct,
            "EQUITY": summary["classified_EQUITY"],
            "REIT": summary["classified_REIT"],
            "SUKUK": summary["classified_SUKUK"],
            "FIXED_INCOME": summary["classified_FIXED_INCOME"],
            "CASH": summary["classified_CASH"],
            "OTHER": summary["classified_OTHER"],
            "UNKNOWN": summary["UNKNOWN"],
        }
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled Security Master listing-fact ingest")
    parser.add_argument("--phase", choices=("preflight", "migrate", "plan", "ingest", "verify", "all"), default="all")
    parser.add_argument("--apply-migration", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    report: dict[str, Any] = {
        "phase": args.phase,
        "planned_source_path": planned_listing_source_path(),
        "nasdaq_calls": 0,
        "sec_calls": 0,
        "fmp_calls": 0,
        "llm_calls": 0,
        "universe_discovery_run": False,
        "participation_run": False,
        "fund_holdings_fetched": False,
    }

    raw_client = create_admin_supabase_client()
    client = SecurityMasterWriteGuard(raw_client)
    url = _supabase_url()
    key = _service_role_key()
    tables = _rest_table_names(url, key) if key else []
    conflicting = [
        name
        for name in tables
        if name != "security_master"
        and any(hint in name.replace("-", "_") for hint in CONFLICTING_NAME_HINTS)
    ]
    probe = _table_probe(client, "security_master")
    queue_before = _queue_snapshot(client)
    invariants_before = _invariants(client, queue_before)
    report["preflight"] = {
        "security_master_exists": probe["exists"],
        "existing_rows": probe["count"],
        "sample_columns": probe["sample_columns"],
        "conflicting_canonical_tables": conflicting,
        "queue": {
            "total": queue_before["total"],
            "status": queue_before["status"],
            "source_universe": queue_before["source_universe"],
        },
        "db_url_present": bool(_resolve_db_url()),
        "table_count": len(tables),
    }
    if args.phase == "preflight":
        print(json.dumps(report, default=str))
        return 0
    if conflicting:
        report["blocked"] = "conflicting canonical table"
        print(json.dumps(report, default=str))
        return 2
    if probe["exists"] is None:
        report["blocked"] = probe["error"]
        print(json.dumps(report, default=str))
        return 2

    if args.phase in {"migrate", "all"} and (args.apply_migration or probe["exists"] is False):
        if probe["exists"] is False:
            report["migration"] = apply_security_master_migration()
            probe = _table_probe(client, "security_master")
            report["migration"]["exists_after"] = probe["exists"]
            report["migration"]["rows_after"] = probe["count"]
            if probe["exists"] is not True:
                report["blocked"] = "migration did not create security_master"
                print(json.dumps(report, default=str))
                return 2
        else:
            report["migration"] = {"applied": False, "reason": "table already exists"}
    elif probe["exists"] is False:
        report["blocked"] = "security_master missing; migration required"
        print(json.dumps(report, default=str))
        return 2
    else:
        report["migration"] = {"applied": False, "reason": "already present"}

    if key:
        openapi_schema = _schema_from_openapi(url, key)
        report["schema"] = openapi_schema
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in (openapi_schema.get("columns") or [])]
        # Empty table may omit columns from a data probe; OpenAPI should list them.
        report["schema"]["missing_required_columns"] = missing_columns

    if args.phase in {"plan", "preflight"}:
        print(json.dumps(report, default=str))
        return 0

    repo = SecurityMasterRepository(client)
    master = SecurityMasterService(repo=repo, include_canonical_static=False)
    feeds = None
    if args.phase in {"ingest", "all"}:
        contact = os.environ.get("SEC_CONTACT_EMAIL") or ""
        listing_client = FreeUniverseClient(contact_email=contact)
        nasdaq_rows, other_rows, sec_rows = fetch_us_equity_listing_feeds(listing_client)
        report["nasdaq_calls"] = 2
        report["sec_calls"] = 1
        feeds = (nasdaq_rows, other_rows, sec_rows)
        first = ingest_merged_us_listing_facts(master, nasdaq_rows, other_rows, sec_rows)
        second = ingest_merged_us_listing_facts(master, nasdaq_rows, other_rows, sec_rows)
        report["first_ingest"] = first.to_dict()
        report["second_replay"] = second.to_dict()

    rows = repo.list_all()
    summary = _fact_summary(rows)
    persisted_master = SecurityMasterService(repo=repo, include_canonical_static=False)
    report["security_master"] = summary
    report["conflicts"] = _conflicts(persisted_master, rows)
    report["sample_equity"] = _sample(rows, "EQUITY")
    report["sample_etf"] = _sample(rows, "ETF")
    name_derived = [
        row
        for row in rows
        if str(row.get("instrument_type") or "") in {"REIT", "SUKUK", "FIXED_INCOME"}
    ]
    report["name_derived_forbidden_types"] = [
        {"identifier": row.get("identifier"), "instrument_type": row.get("instrument_type")}
        for row in name_derived[:20]
    ]
    report["queue_cross_check"] = _queue_cross_check(persisted_master, queue_before["rows"])
    coverage_master = SecurityMasterService(repo=repo, include_canonical_static=True)
    report["fund_coverage_readonly"] = _fund_coverage(client, coverage_master)

    queue_after = _queue_snapshot(client)
    report["invariants_before"] = {key: value for key, value in invariants_before.items() if key != "rows"}
    report["invariants_after"] = _invariants(client, queue_after)
    report["queue_after"] = {
        "total": queue_after["total"],
        "status": queue_after["status"],
        "source_universe": queue_after["source_universe"],
        "participation": queue_after["participation"],
        "research_allowed": queue_after["research_allowed"],
        "symbols_unchanged": queue_before["symbols"] == queue_after["symbols"],
    }
    print(json.dumps(report, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
