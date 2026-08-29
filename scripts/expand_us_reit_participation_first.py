#!/usr/bin/env python3
"""7J.8 Participation-first US REIT expansion.

Enqueue discovery hints, run Participation, classify REIT only after Uygun.
Does not enable hybrid. Does not change methodology or thresholds.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.candidate_repository import CandidateRepository
from repositories.participation_assessment_repository import ParticipationAssessmentRepository
from repositories.security_master_repository import SecurityMasterRepository
from repositories.universe_expansion_repository import UniverseExpansionRepository
from repositories.wealth_portfolio_repository import WealthPortfolioRepository
from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.daily_universe_expansion_service import DailyUniverseExpansionService
from services.economic_classification_ingest import (
    collect_us_listing_identity,
    persist_economic_ingest_plan,
    plan_us_listing_reit_economic_ingest,
)
from services.fmp_client import FMPClient
from services.free_universe_client import FreeUniverseClient
from services.hybrid_exposure_allocation_policy import (
    first_live_blocker,
    resolve_hybrid_allocation_policy,
)
from services.official_fund_holdings_client import OfficialFundHoldingsClient
from services.openfigi_client import (
    ID_CUSIP,
    ID_TICKER,
    MATCH_EXACT_SINGLE,
    MATCH_MULTIPLE,
    OpenFigiClient,
    OpenFigiJob,
    openfigi_exch_code_for_listing,
    resolve_openfigi_api_key,
)
from services.openfigi_evidence_qualification import qualify_mapping
from services.portfolio_allocation_policy_service import PortfolioAllocationPolicyService
from services.reit_evidence_contract import name_is_not_evidence
from services.security_identity_service import identity_service_from_security_master
from services.security_master_contract import IDENTIFIER_TYPE_TICKER, SOURCE_US_LISTING
from services.security_master_listing_ingest import SecurityMasterWriteGuard
from services.security_master_service import production_security_master
from services.strategic_layer_discovery import (
    CLOSED_STRATEGIC_REIT_SYMBOLS,
    actionability_from_candidate,
    may_run_actionability,
    may_run_reit_economic_classification,
    plan_strategic_enqueue,
    select_us_listing_discovery_candidates,
    tickers_from_sec_sic_lookup,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.strategic_layer_discovery_contract import (
    REASON_ROBUST_UW_REAL_ESTATE,
    three_gate_eligibility,
)
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.universe_listing_identity import STRATEGIC_LAYER_DISCOVERY_SOURCE, listing_identity
from services.wealth_goal_planning import planning_conversion
from services.wealth_new_money_allocation import allocate_new_money
from services.wealth_planning_fx import load_planning_fx_schedule

_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})
# Closed 7J.6/7J.7 names are peer seeds only — never rediscovered as candidates.
PEER_SEEDS = tuple(sorted(CLOSED_STRATEGIC_REIT_SYMBOLS | {"EGP", "SUI", "TRNO", "ELS", "WY", "FRMI", "SITC"}))
SEC_REIT_SIC = "6798"
_CIK_IN_ATOM = re.compile(r"cik=0*(\d+)", re.IGNORECASE)


class ReadOnlyGuard:
    def __init__(self, client: Any) -> None:
        self._client = client

    def table(self, name: str):
        return _ReadOnlyTable(self._client.table(name), name)

    def __getattr__(self, name: str):
        return getattr(self._client, name)


class _ReadOnlyTable:
    def __init__(self, inner: Any, table_name: str):
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
        "investment_candidates": _count(client, "investment_candidates"),
        "wealth_portfolios": _count(client, "wealth_portfolios"),
        "wealth_adviser_goals": _count(client, "wealth_adviser_goals"),
        "wealth_transactions": _count(client, "wealth_transactions"),
    }


def _sec_lookup(client: FreeUniverseClient) -> dict[str, dict[str, Any]]:
    rows = client.get_sec_companies()
    return {
        listing_identity(row.get("symbol") or row.get("ticker")): row
        for row in rows
        if listing_identity(row.get("symbol") or row.get("ticker"))
    }


def _listing_index(master: Any, sec_lookup: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for raw in master.repo.list_all():
        if str(raw.get("source") or "") != SOURCE_US_LISTING:
            continue
        if str(raw.get("identifier_type") or "").upper() != IDENTIFIER_TYPE_TICKER:
            continue
        ticker = listing_identity(raw.get("identifier") or raw.get("symbol"))
        if not ticker:
            continue
        meta = dict(raw.get("metadata") or {})
        cik = meta.get("cik") or (sec_lookup.get(ticker) or {}).get("cik")
        index[ticker] = {
            "instrument_type": raw.get("instrument_type"),
            "source": raw.get("source"),
            "exchange": raw.get("exchange") or "",
            "cik": cik,
        }
    for ticker, row in sec_lookup.items():
        if ticker in index and not index[ticker].get("cik"):
            index[ticker]["cik"] = row.get("cik")
    return index


def _fetch_sec_sic_ciks(client: FreeUniverseClient, sic: str = SEC_REIT_SIC) -> list[str]:
    """Official EDGAR SIC universe. Discovery hint only. Fail-soft."""
    ciks: list[str] = []
    seen: set[str] = set()
    try:
        for start in range(0, 800, 100):
            url = (
                "https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&SIC={sic}&owner=include&count=100&start={start}&output=atom"
            )
            time.sleep(0.25)
            response = client.session.get(url, timeout=max(client.timeout, 45))
            if response.status_code != 200:
                break
            page = []
            for raw in _CIK_IN_ATOM.findall(response.text or ""):
                digits = str(int(raw))
                if digits in seen:
                    continue
                seen.add(digits)
                page.append(digits)
            if not page:
                break
            ciks.extend(page)
            if len(page) < 80:
                break
    except Exception:
        return ciks
    return ciks


def _hint_symbols(
    fmp: FMPClient | None,
    *,
    sec_client: FreeUniverseClient,
    sec_lookup: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], dict[str, int]]:
    official = OfficialFundHoldingsClient().fetch("SPRE")
    hints: list[str] = []
    seen: set[str] = set()
    source_counts = Counter()
    for holding in official.holdings:
        ticker = listing_identity(holding.ticker)
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        hints.append(ticker)
        source_counts["spre_constituent"] += 1
    sic_ciks = _fetch_sec_sic_ciks(sec_client)
    source_counts["sec_sic_6798_ciks"] = len(sic_ciks)
    for ticker in tickers_from_sec_sic_lookup(sic_ciks, sec_lookup):
        if ticker in seen:
            continue
        seen.add(ticker)
        hints.append(ticker)
        source_counts["sec_sic_6798"] += 1
    if fmp is not None:
        for seed in PEER_SEEDS:
            try:
                peers = fmp.stock_peers(seed) or []
            except Exception:
                peers = []
            for peer in peers:
                ticker = listing_identity(peer)
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
                hints.append(ticker)
                source_counts["fmp_peers"] += 1
    return hints, dict(source_counts)


def _probe_openfigi(identities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    jobs: list[OpenFigiJob] = []
    tickers: list[str] = []
    for row in identities:
        ticker = row["ticker"]
        exch = openfigi_exch_code_for_listing(row.get("exchange"))
        if ticker and exch:
            jobs.append(OpenFigiJob(ID_TICKER, ticker, exch_code=exch))
            tickers.append(ticker)
        elif ticker and row.get("cusip"):
            jobs.append(OpenFigiJob(ID_CUSIP, str(row["cusip"])))
            tickers.append(ticker)
    client = OpenFigiClient(api_key=resolve_openfigi_api_key(), min_interval_seconds=0.3)
    results = client.map_jobs(tuple(jobs)) if jobs else ()
    qualifications: dict[str, dict[str, Any]] = {}
    retry: list[tuple[str, OpenFigiJob]] = []
    for ticker, result in zip(tickers, results):
        identity = next(item for item in identities if item["ticker"] == ticker)
        name_is_not_evidence(identity.get("issuer_name"))
        qual = qualify_mapping(result)
        if qual.match_status == MATCH_MULTIPLE and identity.get("cusip") and result.job.id_type == ID_TICKER:
            retry.append((ticker, OpenFigiJob(ID_CUSIP, str(identity["cusip"]))))
        qualifications[ticker] = qual.to_dict()
    if retry:
        extra = client.map_jobs(tuple(job for _, job in retry))
        for (ticker, _), result in zip(retry, extra):
            qual = qualify_mapping(result)
            if qual.match_status == MATCH_EXACT_SINGLE:
                qualifications[ticker] = qual.to_dict()
    return qualifications


def _portfolio_bundle(client: Any, user_id: str) -> dict[str, Any]:
    from services.candidate_price_service import CandidatePriceService
    from services.fund_holdings_service import FundHoldingsService
    from services.portfolio_economic_exposure import build_economic_exposure
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
        identity = identity_service_from_security_master(master)
        exposure = build_economic_exposure(
            view,
            fund_snapshots=snapshots,
            assets=wealth.list_assets(),
            positions=wealth.list_positions(),
            security_master=master,
            identity_service=identity,
        )
    return {
        "wealth": wealth,
        "portfolio": portfolio,
        "view": view,
        "snapshots": snapshots,
        "master": master,
        "identity": identity,
        "exposure": exposure,
        "assets": wealth.list_assets(),
        "positions": wealth.list_positions(),
    }


def _new_money(bundle: dict[str, Any], *, hybrid: bool) -> dict[str, Any]:
    wealth = bundle["wealth"]
    portfolio = bundle["portfolio"]
    policy = PortfolioAllocationPolicyService(wealth.client, wealth.user_id).get_policy(
        str(portfolio.get("id") or "")
    )
    candidates = CandidateRepository(wealth.client).get_all(limit=5000) or []
    fx = load_planning_fx_schedule(wealth, str(portfolio.get("id") or ""))
    conversion = planning_conversion(fx.usdtry_for_year(date.today().year))
    plan = allocate_new_money(
        available_amount=Decimal("100000"),
        amount_currency="TRY",
        portfolio_view=bundle["view"],
        policy=policy,
        candidates=candidates,
        conversion=conversion,
        assets=bundle["assets"],
        positions=bundle["positions"],
        fund_snapshots=bundle["snapshots"],
        security_master=bundle["master"],
        identity_service=bundle["identity"],
        enable_hybrid_exposure_allocation=True if hybrid else None,
    )
    return {
        "hybrid_requested": hybrid,
        "hybrid_active": plan.hybrid_allocation_active,
        "production_hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "mode": plan.hybrid_portfolio_mode,
        "allocated": str(plan.total_allocated),
        "residual": str(plan.residual_cash),
        "limitations": list(plan.limitations),
        "blocker": first_live_blocker(plan.limitations),
        "selected": [
            {"symbol": row.symbol, "layer": row.layer, "amount": str(row.amount)}
            for row in plan.recommendations
        ],
        "sukuk_blocks_valid_re": any(
            str(item).startswith("NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER:sukuk")
            for item in plan.limitations
        )
        and any(row.layer == "real_estate" for row in plan.recommendations),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enqueue", action="store_true")
    parser.add_argument("--run-participation", action="store_true")
    parser.add_argument("--classify-uygun", action="store_true")
    parser.add_argument("--scan-uygun", action="store_true")
    parser.add_argument("--hybrid-uat", action="store_true")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    readonly = ReadOnlyGuard(raw)
    master = production_security_master(readonly)
    sec_email = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    queue_repo = UniverseExpansionRepository(readonly)
    queue_rows = queue_repo.list_all()
    continue_existing = bool(args.run_participation and not args.enqueue)
    sec_client = FreeUniverseClient(contact_email=sec_email)
    sec_lookup = _sec_lookup(sec_client)
    hints: list[str] = []
    hint_sources: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    if continue_existing:
        hint_sources = {"skipped_rediscovery": 1}
        proposed = [
            listing_identity(row.get("symbol"))
            for row in queue_rows
            if str(row.get("status") or "") in {"PENDING", "RETRYABLE"}
            and str(row.get("source_universe") or "") == STRATEGIC_LAYER_DISCOVERY_SOURCE
            and listing_identity(row.get("symbol"))
            and listing_identity(row.get("symbol")) not in CLOSED_STRATEGIC_REIT_SYMBOLS
        ]
    else:
        listing_rows = _listing_index(master, sec_lookup)
        fmp = None
        try:
            fmp = FMPClient.from_env()
        except Exception:
            fmp = None
        hints, hint_sources = _hint_symbols(fmp, sec_client=sec_client, sec_lookup=sec_lookup)
        queued = [str(row.get("symbol") or "") for row in queue_rows]
        selected = list(
            select_us_listing_discovery_candidates(
                hints,
                listing_rows=listing_rows,
                queued_symbols=queued,
                limit=args.limit,
            )
        )
        proposed = [row["symbol"] for row in selected]
    enqueue_plan = plan_strategic_enqueue(proposed, repo=queue_repo, dry_run=True)
    report: dict[str, Any] = {
        "closed": sorted(CLOSED_STRATEGIC_REIT_SYMBOLS),
        "hints": len(hints),
        "hint_sources": hint_sources,
        "discovered_full": [row["symbol"] for row in selected],
        "fully_supported": len(selected),
        "enqueue_dry_run": enqueue_plan.to_dict(),
        "discovery_reason": REASON_ROBUST_UW_REAL_ESTATE,
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "pre_invariants": _invariants(readonly, queue_rows),
    }
    writes: dict[str, Any] = {}

    if args.enqueue:
        live_queue = UniverseExpansionRepository(raw)
        live_plan = plan_strategic_enqueue(proposed, repo=live_queue, dry_run=False)
        writes["enqueue"] = live_plan.to_dict()
        report["enqueue"] = live_plan.to_dict()

    if args.run_participation:
        live_queue = UniverseExpansionRepository(raw)
        live_rows = live_queue.list_all()
        extra = [
            listing_identity(row.get("symbol"))
            for row in live_rows
            if str(row.get("status") or "") in {"PENDING", "RETRYABLE"}
            and str(row.get("source_universe") or "") != STRATEGIC_LAYER_DISCOVERY_SOURCE
        ]
        if extra:
            writes["participation"] = {"ran": False, "reason": "OTHER_ELIGIBLE_QUEUE_ROWS", "extra": extra}
        else:
            from services.sec_financial_client import SECFinancialClient

            fmp_client = FMPClient.from_env()
            sec = SECFinancialClient(contact_email=sec_email)
            service = DailyUniverseExpansionService(queue_repo=live_queue)
            details: list[dict[str, Any]] = []
            started = 0
            last_stop = ""
            for _ in range(max(args.limit, 1)):
                pending_now = [
                    listing_identity(row.get("symbol"))
                    for row in live_queue.list_all()
                    if str(row.get("status") or "") in {"PENDING", "RETRYABLE"}
                    and str(row.get("source_universe") or "") == STRATEGIC_LAYER_DISCOVERY_SOURCE
                ]
                if not pending_now:
                    break
                run = service.run_once(
                    max_symbols=1,
                    dry_run=False,
                    seed_if_empty=False,
                    fmp_client=fmp_client,
                    sec_client=sec,
                    participation_repo=ParticipationAssessmentRepository(raw),
                    candidate_repo=CandidateRepository(raw),
                    sec_ticker_lookup=sec_lookup,
                )
                started += run.symbols_started
                last_stop = run.stop_reason
                details.extend(item.to_dict() for item in run.symbol_details)
                if run.symbols_started == 0:
                    break
            writes["participation"] = {
                "ran": True,
                "stop_reason": last_stop,
                "symbols_started": started,
                "details": details,
            }

    snap_repo = ParticipationAssessmentRepository(readonly)
    live_queue_rows = UniverseExpansionRepository(readonly).list_all()
    if continue_existing or args.run_participation:
        proposed = [
            listing_identity(row.get("symbol"))
            for row in live_queue_rows
            if str(row.get("source_universe") or "") == STRATEGIC_LAYER_DISCOVERY_SOURCE
            and listing_identity(row.get("symbol"))
            and listing_identity(row.get("symbol")) not in CLOSED_STRATEGIC_REIT_SYMBOLS
        ]
    qmap = {listing_identity(row.get("symbol")): row for row in live_queue_rows}
    participation_rows = {}
    uygun: list[str] = []
    for symbol in proposed:
        qrow = qmap.get(symbol) or {}
        snap = snap_repo.get_latest(symbol) if qrow else None
        status = str((qrow or {}).get("participation_status") or "")
        payload = (snap or {}).get("assessment_payload") or {}
        fin = payload.get("financial_screen_result") or {}
        biz = payload.get("business_screen_result") or {}
        participation_rows[symbol] = {
            "status": status or "NOT_RUN",
            "research_allowed": qrow.get("research_allowed"),
            "financial_overall": (snap or {}).get("financial_overall_outcome") or fin.get("overall_outcome"),
            "business_overall": (snap or {}).get("business_overall_outcome") or biz.get("overall_outcome"),
            "missing_capabilities": (snap or {}).get("missing_capabilities") or [],
            "hard_fail": str((snap or {}).get("financial_overall_outcome") or "") == "FAIL"
            or str((snap or {}).get("business_overall_outcome") or "") == "FAIL",
        }
        if may_run_reit_economic_classification(participation_status=status):
            uygun.append(symbol)
    report["participation"] = participation_rows
    report["uygun"] = uygun

    classification = {}
    if args.classify_uygun and uygun:
        identities = [collect_us_listing_identity(master, symbol) for symbol in uygun]
        qualifications = _probe_openfigi(identities)
        existing = SecurityMasterRepository(readonly).list_all()
        plan = plan_us_listing_reit_economic_ingest(
            identities, qualifications, existing_rows=existing
        )
        classification = {
            "write_gate": plan.write_gate,
            "write_gate_reasons": list(plan.write_gate_reasons),
            "rows": [row.to_dict() for row in plan.rows],
            "pass": [row.ticker for row in plan.rows if row.economic_layer == "real_estate"],
        }
        if plan.write_gate == "PASS":
            from services.security_master_service import SecurityMasterService

            live = SecurityMasterService(
                repo=SecurityMasterRepository(SecurityMasterWriteGuard(raw)),
                include_canonical_static=False,
            )
            first = persist_economic_ingest_plan(plan, security_master=live)
            after = SecurityMasterRepository(readonly).list_all()
            replay = plan_us_listing_reit_economic_ingest(
                identities, qualifications, existing_rows=after
            )
            second = persist_economic_ingest_plan(replay, security_master=live)
            classification["writes"] = {
                "inserted": first.inserted,
                "updated": first.updated,
                "replay_inserted": second.inserted,
                "replay_updated": second.updated,
                "replay_unchanged": second.unchanged,
            }
            for symbol in uygun:
                classification.setdefault("instrument_after", {})[symbol] = {
                    "instrument_type": live.resolve_security(symbol).instrument_type,
                    "source": live.resolve_security(symbol).source,
                }
    report["classification"] = classification

    scan = {}
    if args.scan_uygun and uygun:
        from services.participation_authority import resolve_authoritative_participation
        from services.scanner_v8_engine import ScannerV8Engine
        from services.sec_financial_client import SECFinancialClient

        fmp_client = FMPClient.from_env()
        sec = SECFinancialClient(contact_email=sec_email)
        engine = ScannerV8Engine(fmp_client, sec)
        live_candidates = CandidateRepository(raw)
        snapshots = ParticipationAssessmentRepository(raw).list_latest_by_symbol()
        refreshed_identity = identity_service_from_security_master(
            production_security_master(readonly)
        )
        class_pass = set(classification.get("pass") or [])
        for symbol in uygun:
            layer = refreshed_identity.resolve_economic_layer([symbol]).economic_layer
            if layer == "real_estate":
                class_pass.add(symbol)
            if not may_run_actionability(
                participation_status=PARTICIPATION_STATUS_UYGUN,
                classification_status="PASS" if symbol in class_pass else "FAIL",
            ):
                scan[symbol] = {"ran": False, "reason": "CLASSIFICATION_NOT_PASS"}
                continue
            if layer != "real_estate":
                scan[symbol] = {"ran": False, "reason": "ECONOMIC_LAYER_NOT_REAL_ESTATE"}
                continue
            qrow = UniverseExpansionRepository(raw).get_by_symbol(symbol) or {}
            authority = resolve_authoritative_participation(
                symbol,
                candidate=live_candidates.get_by_symbol(symbol),
                snapshot=snapshots.get(symbol),
            )
            if not authority.scanner_allowed:
                scan[symbol] = {"ran": False, "reason": authority.skip_reason}
                continue
            result = engine.analyze(
                symbol=symbol,
                participation_status=authority.status,
                participation_score=100 if authority.approved else 60,
            )
            candidate = result["candidate"]
            should_write = (
                not result["excluded"]
                and candidate.get("data_completeness", 0) >= 65
                and candidate.get("conviction_score", 0) >= 60
                and candidate.get("decision_label") not in {"ŞİMDİLİK UZAK DUR", "VERİ EKSİK — ÖN ELEME"}
            )
            if should_write:
                live_candidates.upsert_by_symbol(candidate)
            scan[symbol] = {
                "ran": True,
                "decision": candidate.get("decision_label") or candidate.get("decision"),
                "completeness": candidate.get("data_completeness"),
                "actionable": is_actionable_opportunity(candidate),
                "persisted": should_write,
                "excluded": result.get("excluded"),
            }
    report["scan"] = scan

    refreshed_master = production_security_master(readonly)
    refreshed_identity = identity_service_from_security_master(refreshed_master)
    cand_map = {
        listing_identity(row.get("symbol")): row
        for row in (CandidateRepository(readonly).get_all(limit=5000) or [])
    }
    qmap = {
        listing_identity(row.get("symbol")): row
        for row in UniverseExpansionRepository(readonly).list_all()
    }
    matrix = {}
    fillers = []
    for symbol in proposed:
        qrow = qmap.get(symbol) or {}
        status = str(qrow.get("participation_status") or "")
        layer = refreshed_identity.resolve_economic_layer([symbol]).economic_layer
        classification_status = "PASS" if layer == "real_estate" else "FAIL"
        if not may_run_reit_economic_classification(participation_status=status):
            if layer != "real_estate":
                classification_status = "NOT_RUN"
        actionability = actionability_from_candidate(cand_map.get(symbol))
        gate = three_gate_eligibility(
            classification_status="PASS" if classification_status == "PASS" else "FAIL",
            participation_status=status,
            actionability=actionability,
            discovery_reason=REASON_ROBUST_UW_REAL_ESTATE,
        )
        if gate == "ELIGIBLE_FILLER":
            fillers.append(symbol)
        matrix[symbol] = {
            "classification": classification_status,
            "participation": status or "NOT_RUN",
            "research_allowed": qrow.get("research_allowed"),
            "actionability": actionability,
            "economic_layer": layer,
            "instrument_type": refreshed_master.resolve_security(symbol).instrument_type,
            "eligible": gate == "ELIGIBLE_FILLER",
        }
    report["three_gate"] = matrix
    report["eligible_real_estate_fillers"] = fillers
    report["writes"] = writes
    report["post_invariants"] = _invariants(
        readonly, UniverseExpansionRepository(readonly).list_all()
    )
    if args.hybrid_uat or fillers:
        bundle = _portfolio_bundle(readonly, _user_id(raw))
        report["hybrid_uat"] = _new_money(bundle, hybrid=True)
        report["new_money_off"] = _new_money(bundle, hybrid=False)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
