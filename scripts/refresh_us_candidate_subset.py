#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from repositories.sec_company_facts_cache import SecCompanyFactsCache
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.candidate_identity import select_canonical_candidate
from services.fmp_client import FMPClient
from services.free_universe_client import FreeUniverseClient
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_UYGUN,
)
from services.scanner_v8_engine import ScannerV8Engine
from services.sec_financial_client import SECFinancialClient
from services.security_intelligence_service import (
    explicit_persisted_research_allowed,
    participation_from_sources,
)
from services.security_master_contract import (
    INSTRUMENT_EQUITY,
    RESOLUTION_RESOLVED,
    SOURCE_BIST,
)
from services.security_master_service import production_security_master


WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})
ALLOWED_WRITE_TABLES = {
    "investment_candidates": frozenset({"update"}),
}


class CandidateRefreshWriteGuard:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.blocked: list[str] = []
        self.allowed_write_attempts: list[str] = []

    def table(self, name: str):
        return _GuardedTable(
            self,
            self._client.table(name),
            name,
        )

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _GuardedTable:
    def __init__(
        self,
        guard: CandidateRefreshWriteGuard,
        inner: Any,
        name: str,
    ) -> None:
        self._guard = guard
        self._inner = inner
        self._name = name

    def __getattr__(self, name: str):
        if name in WRITE_METHODS:
            allowed = ALLOWED_WRITE_TABLES.get(
                self._name,
                frozenset(),
            )

            if name not in allowed:
                def blocked(*_args: Any, **_kwargs: Any):
                    attempt = f"{self._name}.{name}"
                    self._guard.blocked.append(attempt)
                    raise RuntimeError(
                        f"blocked write {attempt}"
                    )

                return blocked

            inner_method = getattr(self._inner, name)

            def permitted(*args: Any, **kwargs: Any):
                self._guard.allowed_write_attempts.append(
                    f"{self._name}.{name}"
                )
                return inner_method(*args, **kwargs)

            return permitted

        return getattr(self._inner, name)


def parse_args(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(
        description=(
            "Bounded US candidate refresh for SI rollout."
        )
    )
    parser.add_argument("--symbols", required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--persist-candidate",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=2,
    )
    return parser.parse_args(argv)


def _number(value: Any, default: float) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_identity(resolution: Any) -> bool:
    if resolution is None:
        return False
    if str(
        getattr(resolution, "status", "") or ""
    ) != RESOLUTION_RESOLVED:
        return False
    if str(
        getattr(resolution, "instrument_type", "") or ""
    ) != INSTRUMENT_EQUITY:
        return False
    if str(
        getattr(resolution, "source", "") or ""
    ) == SOURCE_BIST:
        return False
    return True


def _degradable_provider_warnings(
    endpoint_status: dict[str, Any],
    errors: list[Any],
) -> tuple[bool, list[str]]:
    """
    Candidate refresh may continue only for the narrowly approved
    FMP degradation path:

    - SEC Company Facts succeeded.
    - FMP profile succeeded.
    - FMP quote and/or ratios_ttm may be PLAN_RESTRICTED.
    - No other provider endpoint may have failed.
    - Every scanner warning must belong to the degraded FMP endpoint(s).

    Candidate critical-data gates are still evaluated afterwards.
    """
    status = dict(endpoint_status or {})
    warnings = [str(value) for value in errors or []]

    if not warnings:
        return True, []

    if status.get("sec_companyfacts") != "OK":
        return False, warnings

    if status.get("fmp_profile") != "OK":
        return False, warnings

    degradable_keys = {
        "fmp_quote": "FMP quote:",
        "fmp_ratios_ttm": "FMP ratios_ttm:",
    }

    degraded_prefixes: list[str] = []

    for key, prefix in degradable_keys.items():
        value = status.get(key)

        if value == "PLAN_RESTRICTED":
            degraded_prefixes.append(prefix)
            continue

        if value not in (None, "OK"):
            return False, warnings

    if not degraded_prefixes:
        return False, warnings

    for warning in warnings:
        if not any(
            warning.startswith(prefix)
            for prefix in degraded_prefixes
        ):
            return False, warnings

    return True, warnings


def _provider_calls_observed(
    endpoint_status: dict[str, Any],
) -> int:
    provider_keys = {
        "fmp_profile",
        "fmp_quote",
        "fmp_ratios_ttm",
        "sec_companyfacts",
    }
    return sum(
        1
        for key, value in dict(endpoint_status or {}).items()
        if key in provider_keys
        and str(value or "").strip() == "OK"
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    symbols = tuple(
        dict.fromkeys(
            item.strip().upper()
            for item in args.symbols.split(",")
            if item.strip()
        )
    )

    if not symbols:
        raise SystemExit(
            "At least one explicit symbol is required."
        )

    if len(symbols) > max(1, int(args.max_symbols)):
        raise SystemExit(
            "BROAD_SCOPE_REFUSED:"
            f"{len(symbols)}>{args.max_symbols}"
        )

    live_write = bool(
        args.execute
        and args.persist_candidate
        and args.allow_live
    )

    if args.persist_candidate and not args.allow_live:
        raise SystemExit(
            "LIVE_CANDIDATE_PERSIST_UNSAFE"
        )

    if args.persist_candidate and not args.execute:
        raise SystemExit(
            "LIVE_CANDIDATE_PERSIST_REQUIRES_EXECUTE"
        )

    from services.supabase_admin_client import (
        apply_local_secrets_to_env,
        create_admin_supabase_client,
    )

    apply_local_secrets_to_env()

    raw = create_admin_supabase_client()
    client = CandidateRefreshWriteGuard(raw)

    candidates = CandidateRepository(client)
    participation_repo = ParticipationAssessmentRepository(
        client
    )
    queue_repo = UniverseExpansionRepository(client)
    master = production_security_master(client)

    sec_email = (
        os.environ.get("SEC_CONTACT_EMAIL") or ""
    ).strip()

    if args.execute and not sec_email:
        raise SystemExit(
            "SEC_CONTACT_EMAIL_REQUIRED"
        )

    fmp = None
    sec = None
    scanner = None
    sec_index: dict[str, dict[str, Any]] = {}

    cache = SecCompanyFactsCache()

    if args.execute:
        fmp = FMPClient.from_env()
        reset = getattr(fmp, "reset_scan_state", None)
        if callable(reset):
            reset()

        sec = SECFinancialClient(
            contact_email=sec_email
        )

        scanner = ScannerV8Engine(
            fmp,
            sec,
            sec_company_facts_cache=cache,
        )

        sec_index = {
            str(row.get("symbol") or "")
            .strip()
            .upper(): row
            for row in FreeUniverseClient(
                contact_email=sec_email
            ).get_sec_companies()
            if row.get("symbol")
        }

    items = []

    for symbol in symbols:
        item = {
            "symbol": symbol,
            "status": "",
            "reason": "",
            "provider_calls_observed": 0,
            "candidate_write": False,
            "financial_period_end": None,
            "freshness_status": None,
            "data_completeness": None,
            "error": "",
        }

        try:
            existing = select_canonical_candidate(
                candidates.list_by_symbol(symbol),
                preferred_market="US",
            )

            if not existing or not existing.get("id"):
                item["status"] = "BLOCKED"
                item["reason"] = "CANONICAL_CANDIDATE_MISSING"
                items.append(item)
                continue

            snapshot = participation_repo.get_latest(
                symbol
            )

            try:
                queue_row = queue_repo.get_by_symbol(
                    symbol
                )
            except Exception:
                queue_row = None

            research_allowed = (
                explicit_persisted_research_allowed(
                    queue_row=queue_row,
                    snapshot=snapshot,
                )
            )

            participation = participation_from_sources(
                queue_or_snapshot=snapshot,
                candidate=existing,
                research_allowed=research_allowed,
            )

            if (
                participation.status
                != PARTICIPATION_STATUS_UYGUN
            ):
                item["status"] = "BLOCKED"
                item["reason"] = "PARTICIPATION_NOT_UYGUN"
                items.append(item)
                continue

            if research_allowed is not True:
                item["status"] = "BLOCKED"
                item["reason"] = "RESEARCH_NOT_ALLOWED"
                items.append(item)
                continue

            resolution = master.resolve_security(symbol)

            if not _safe_identity(resolution):
                item["status"] = "BLOCKED"
                item["reason"] = "SECURITY_MASTER_IDENTITY_UNSAFE"
                items.append(item)
                continue

            if not args.execute:
                item["status"] = "PLANNED"
                item["reason"] = "PLAN_ONLY_NO_PROVIDER_CALLS"
                items.append(item)
                continue

            listing = sec_index.get(symbol)

            if not listing:
                item["status"] = "BLOCKED"
                item["reason"] = "SEC_LISTING_MISSING"
                items.append(item)
                continue

            cik = listing.get("cik")

            if cik in (None, ""):
                item["status"] = "BLOCKED"
                item["reason"] = "SEC_CIK_MISSING"
                items.append(item)
                continue

            assert scanner is not None

            result = scanner.analyze(
                symbol=symbol,
                cik=cik,
                company_name=(
                    listing.get("company_name")
                    or existing.get("company_name")
                    or symbol
                ),
                exchange=(
                    listing.get("exchange")
                    or existing.get("exchange_name")
                ),
                is_etf=False,
                participation_status=(
                    PARTICIPATION_STATUS_UYGUN
                ),
                participation_score=_number(
                    (snapshot or {}).get(
                        "participation_score"
                    )
                    or (snapshot or {}).get("score"),
                    100.0,
                ),
                portfolio_fit=_number(
                    existing.get(
                        "portfolio_fit_score"
                    ),
                    55.0,
                ),
            )

            endpoint_status = dict(
                result.get("endpoint_status") or {}
            )

            item["provider_calls_observed"] = (
                _provider_calls_observed(
                    endpoint_status
                )
            )

            if result.get("excluded"):
                item["status"] = "BLOCKED"
                item["reason"] = "SCANNER_EXCLUDED"
                items.append(item)
                continue

            errors = list(result.get("errors") or [])

            provider_warnings_degradable, preserved_warnings = (
                _degradable_provider_warnings(
                    endpoint_status,
                    errors,
                )
            )

            if errors and not provider_warnings_degradable:
                item["status"] = "BLOCKED"
                item["reason"] = "SCANNER_PROVIDER_WARNINGS"
                item["error"] = " | ".join(
                    str(value) for value in errors
                )
                items.append(item)
                continue

            if preserved_warnings:
                item["error"] = " | ".join(
                    preserved_warnings
                )

            refreshed = dict(
                result.get("candidate") or {}
            )

            period = str(
                refreshed.get("financial_period_end")
                or ""
            ).strip()

            freshness = str(
                refreshed.get("freshness_status")
                or ""
            ).strip().upper()

            completeness = refreshed.get(
                "data_completeness"
            )

            item["financial_period_end"] = (
                period or None
            )
            item["freshness_status"] = (
                freshness or None
            )
            item["data_completeness"] = completeness

            if not period:
                item["status"] = "BLOCKED"
                item["reason"] = "FINANCIAL_PERIOD_MISSING"
                items.append(item)
                continue

            if freshness != "FRESH":
                item["status"] = "BLOCKED"
                item["reason"] = (
                    "REFRESHED_CANDIDATE_NOT_FRESH"
                )
                items.append(item)
                continue

            if float(completeness or 0) < 65.0:
                item["status"] = "BLOCKED"
                item["reason"] = (
                    "REFRESHED_CANDIDATE_TOO_SPARSE"
                )
                items.append(item)
                continue

            if not live_write:
                item["status"] = "WOULD_UPDATE"
                items.append(item)
                continue

            candidates.update(
                str(existing["id"]),
                refreshed,
            )

            item["candidate_write"] = True
            item["status"] = "UPDATED"
            items.append(item)

        except Exception as exc:
            item["status"] = "ERROR"
            item["reason"] = type(exc).__name__
            item["error"] = (
                f"{type(exc).__name__}: {exc}"
            )
            items.append(item)

    payload = {
        "job_name": "us_candidate_subset_refresh",
        "execute_providers": bool(args.execute),
        "persist_candidate": bool(
            args.persist_candidate
        ),
        "allow_live": bool(args.allow_live),
        "symbols_checked": len(symbols),
        "provider_calls_observed": sum(
            int(
                item.get(
                    "provider_calls_observed"
                )
                or 0
            )
            for item in items
        ),
        "writes": sum(
            bool(item.get("candidate_write"))
            for item in items
        ),
        "updated": sum(
            item.get("status") == "UPDATED"
            for item in items
        ),
        "blocked": sum(
            item.get("status") == "BLOCKED"
            for item in items
        ),
        "errors": sum(
            item.get("status") == "ERROR"
            for item in items
        ),
        "items": items,
        "blocked_writes": list(client.blocked),
        "allowed_write_attempts": list(
            client.allowed_write_attempts
        ),
    }

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    if client.blocked:
        return 2

    if payload["errors"] or payload["blocked"]:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
