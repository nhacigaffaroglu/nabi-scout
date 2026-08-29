#!/usr/bin/env python3
"""7J.6 US-listed REIT evidence + controlled Participation onboarding.

Security Master / queue / Participation / candidate writes only.
Does not enable hybrid. Does not change targets, cash policy, or SPSK.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
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
    US_REIT_ONBOARDING_TARGETS,
    collect_us_listing_identity,
    persist_economic_ingest_plan,
    plan_us_listing_reit_economic_ingest,
)
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
from services.reit_evidence_contract import is_explicit_structured_reit, name_is_not_evidence
from services.security_identity_service import identity_service_from_security_master
from services.security_master_listing_ingest import SecurityMasterWriteGuard
from services.security_master_service import production_security_master
from services.strategic_layer_discovery import actionability_from_candidate, plan_strategic_enqueue
from services.strategic_layer_discovery_contract import (
    ACTIONABILITY_NOT_RUN,
    CLASSIFICATION_FAIL,
    CLASSIFICATION_PASS,
    REASON_ROBUST_UW_REAL_ESTATE,
    three_gate_eligibility,
)
from services.supabase_admin_client import apply_local_secrets_to_env, create_admin_supabase_client
from services.universe_listing_identity import STRATEGIC_LAYER_DISCOVERY_SOURCE, listing_identity
from services.wealth_goal_planning import planning_conversion
from services.wealth_new_money_allocation import allocate_new_money
from services.wealth_planning_fx import load_planning_fx_schedule

_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})


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


def _official_ids() -> dict[str, dict[str, str]]:
    official = OfficialFundHoldingsClient().fetch("SPRE")
    mapped: dict[str, dict[str, str]] = {}
    for holding in official.holdings:
        ticker = listing_identity(holding.ticker)
        if ticker not in US_REIT_ONBOARDING_TARGETS:
            continue
        mapped[ticker] = {
            "cusip": str(holding.cusip_raw or "").strip().upper(),
            "sedol": "",
        }
    return mapped


def _probe_openfigi(
    identities: list[dict[str, Any]],
) -> dict[str, Any]:
    jobs: list[OpenFigiJob] = []
    job_tickers: list[str] = []
    for row in identities:
        ticker = row["ticker"]
        exch = openfigi_exch_code_for_listing(row.get("exchange"))
        if ticker and exch:
            jobs.append(OpenFigiJob(ID_TICKER, ticker, exch_code=exch))
            job_tickers.append(ticker)
        elif ticker and row.get("cusip"):
            jobs.append(OpenFigiJob(ID_CUSIP, str(row["cusip"])))
            job_tickers.append(ticker)
    client = OpenFigiClient(api_key=resolve_openfigi_api_key(), min_interval_seconds=0.3)
    results = client.map_jobs(tuple(jobs)) if jobs else ()
    qualifications: dict[str, dict[str, Any]] = {}
    retry: list[tuple[str, OpenFigiJob]] = []
    for ticker, result in zip(job_tickers, results):
        identity = next(item for item in identities if item["ticker"] == ticker)
        name_is_not_evidence(identity.get("issuer_name"))
        qual = qualify_mapping(result)
        payload = qual.to_dict()
        if (
            qual.match_status == MATCH_MULTIPLE
            and identity.get("cusip")
            and result.job.id_type == ID_TICKER
        ):
            retry.append((ticker, OpenFigiJob(ID_CUSIP, str(identity["cusip"]))))
        qualifications[ticker] = payload
    if retry:
        extra = client.map_jobs(tuple(job for _, job in retry))
        for (ticker, _), result in zip(retry, extra):
            qual = qualify_mapping(result)
            if qual.match_status == MATCH_EXACT_SINGLE:
                qualifications[ticker] = qual.to_dict()
    return qualifications


def _classification_status(plan_row: Any) -> str:
    if plan_row.action in {"INSERT", "NOOP"} and plan_row.economic_layer == "real_estate":
        return CLASSIFICATION_PASS
    return CLASSIFICATION_FAIL


def _portfolio_bundle(raw: Any, client: Any, user_id: str) -> dict[str, Any]:
    from services.candidate_price_service import CandidatePriceService
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
        from services.fund_holdings_service import FundHoldingsService

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
    layers = {
        row.bucket_id: float(row.observable_weight_pct or 0.0) for row in exposure.buckets
    }
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
        "summary": {
            "id": portfolio.get("id"),
            "name": portfolio.get("name"),
            "mv": view.priced_total_market_value,
            "layers": layers,
        },
    }


def _new_money(bundle: dict[str, Any], *, hybrid: bool) -> dict[str, Any]:
    from services.exposure_determinacy_diagnostics import eligible_fill_assets
    from services.portfolio_allocation_intelligence import build_allocation_intelligence
    from services.wealth_new_money_allocation import _allocation_buckets_from_exposure

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
        identity_service=bundle["identity"],
        enable_hybrid_exposure_allocation=True if hybrid else None,
    )
    fill_assets = eligible_fill_assets(
        bundle["exposure"].instruments,
        extra_symbols=candidates,
        assets=bundle["assets"],
    )
    intelligence = build_allocation_intelligence(
        view,
        policy=policy,
        assets=bundle["assets"],
        positions=bundle["positions"],
        exposure_buckets=_allocation_buckets_from_exposure(bundle["exposure"]),
        exposure_view=bundle["exposure"],
        candidates=list(candidates),
    )
    diagnostics = intelligence.exposure_diagnostics
    diag = diagnostics.to_dict() if diagnostics is not None else {}
    selected = [
        {
            "symbol": row.symbol,
            "layer": row.layer,
            "amount": str(row.amount),
        }
        for row in plan.recommendations
    ]
    sukuk_blocks_re = False
    blocker = first_live_blocker(plan.limitations)
    re_allocated = any(row.layer == "real_estate" for row in plan.recommendations)
    if re_allocated and any(
        str(item).startswith("UNFILLED_UNDERWEIGHT:sukuk") for item in plan.limitations
    ):
        sukuk_blocks_re = False
    elif str(blocker or "").startswith("NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER:sukuk"):
        sukuk_blocks_re = True
    return {
        "hybrid_requested": hybrid,
        "hybrid_active": plan.hybrid_allocation_active,
        "production_hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "mode": plan.hybrid_portfolio_mode,
        "allocated": str(plan.total_allocated),
        "residual": str(plan.residual_cash),
        "limitations": list(plan.limitations),
        "blocker": blocker,
        "robust_underweight": diag.get("robust_underweight_layers") or [],
        "fillable": diag.get("fillable_robust_underweight_layers") or [],
        "unfillable": diag.get("unfillable_robust_underweight_layers") or [],
        "selected": selected,
        "sukuk_blocks_valid_re": sukuk_blocks_re,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-classification", action="store_true")
    parser.add_argument("--enqueue", action="store_true")
    parser.add_argument("--run-participation", action="store_true")
    parser.add_argument("--scan-uygun", action="store_true")
    parser.add_argument("--hybrid-uat", action="store_true")
    args = parser.parse_args()

    apply_local_secrets_to_env()
    raw = create_admin_supabase_client()
    readonly = ReadOnlyGuard(raw)
    master = production_security_master(readonly)
    official_ids = _official_ids()
    identities = [
        collect_us_listing_identity(
            master,
            ticker,
            official_cusip=(official_ids.get(ticker) or {}).get("cusip", ""),
            official_sedol=(official_ids.get(ticker) or {}).get("sedol", ""),
        )
        for ticker in US_REIT_ONBOARDING_TARGETS
    ]
    qualifications = _probe_openfigi(identities)
    existing = SecurityMasterRepository(readonly).list_all()
    plan = plan_us_listing_reit_economic_ingest(
        identities, qualifications, existing_rows=existing
    )
    queue_repo = UniverseExpansionRepository(readonly)
    queue_rows = queue_repo.list_all()
    candidates = CandidateRepository(readonly).get_all(limit=5000) or []
    candidate_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row for row in candidates
    }
    queue_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row for row in queue_rows
    }
    pass_symbols = [
        row.ticker for row in plan.rows if _classification_status(row) == CLASSIFICATION_PASS
    ]
    enqueue_candidates = []
    already_evaluated = []
    for ticker in pass_symbols:
        qrow = queue_by_symbol.get(ticker)
        if qrow and str(qrow.get("participation_status") or "").strip():
            already_evaluated.append(ticker)
            continue
        enqueue_candidates.append(ticker)
    enqueue_plan = plan_strategic_enqueue(
        enqueue_candidates,
        repo=queue_repo,
        dry_run=True,
    )
    report: dict[str, Any] = {
        "targets": list(US_REIT_ONBOARDING_TARGETS),
        "identity": identities,
        "identity_exact": [row["ticker"] for row in identities if row["identity_status"] == "exact"],
        "identity_ambiguous": [
            row["ticker"] for row in identities if row["identity_status"] == "ambiguous"
        ],
        "identity_unmapped": [
            row["ticker"] for row in identities if row["identity_status"] == "unmapped"
        ],
        "openfigi": qualifications,
        "classification": [row.to_dict() | {"classification": _classification_status(row)} for row in plan.rows],
        "classification_pass": pass_symbols,
        "classification_fail": [
            row.ticker for row in plan.rows if _classification_status(row) != CLASSIFICATION_PASS
        ],
        "write_gate": plan.write_gate,
        "write_gate_reasons": list(plan.write_gate_reasons),
        "discovery_source": STRATEGIC_LAYER_DISCOVERY_SOURCE,
        "discovery_reason": REASON_ROBUST_UW_REAL_ESTATE,
        "already_participation_evaluated": already_evaluated,
        "enqueue": enqueue_plan.to_dict(),
        "hybrid_enabled": resolve_hybrid_allocation_policy().enabled,
        "pre_invariants": _invariants(readonly, queue_rows),
    }
    for row in identities:
        ticker = row["ticker"]
        qrow = queue_by_symbol.get(ticker)
        crow = candidate_by_symbol.get(ticker)
        qual = qualifications.get(ticker) or {}
        report.setdefault("per_target", {})[ticker] = {
            "identity": row["identity_status"],
            "instrument_type": row["instrument_type"],
            "economic_layer_proposal": (
                "real_estate"
                if is_explicit_structured_reit(qual.get("securityType"), qual.get("securityType2"))
                else ""
            ),
            "evidence": {
                "source": "openfigi_mapping",
                "match_status": qual.get("match_status"),
                "securityType": qual.get("securityType"),
                "securityType2": qual.get("securityType2"),
                "figi": qual.get("figi"),
            },
            "queue": None
            if qrow is None
            else {
                "status": qrow.get("status"),
                "source_universe": qrow.get("source_universe"),
                "participation_status": qrow.get("participation_status"),
                "research_allowed": qrow.get("research_allowed"),
            },
            "candidate": None
            if crow is None
            else {
                "decision": crow.get("decision_label") or crow.get("decision"),
                "actionable": is_actionable_opportunity(crow),
            },
        }

    writes = {"classification": {}, "enqueue": {}, "participation": {}, "scan": {}}
    if args.apply_classification:
        if plan.write_gate != "PASS":
            raise SystemExit(f"write gate failed: {plan.write_gate_reasons}")
        guard = SecurityMasterWriteGuard(raw)
        from services.security_master_service import SecurityMasterService

        live = SecurityMasterService(
            repo=SecurityMasterRepository(guard), include_canonical_static=False
        )
        first = persist_economic_ingest_plan(plan, security_master=live)
        after = SecurityMasterRepository(readonly).list_all()
        replay = plan_us_listing_reit_economic_ingest(
            identities, qualifications, existing_rows=after
        )
        second = persist_economic_ingest_plan(replay, security_master=live)
        writes["classification"] = {
            "inserted": first.inserted,
            "updated": first.updated,
            "unchanged": first.unchanged,
            "replay_inserted": second.inserted,
            "replay_updated": second.updated,
            "replay_unchanged": second.unchanged,
            "replay_gate": replay.write_gate,
        }
        for ticker in US_REIT_ONBOARDING_TARGETS:
            resolved = live.resolve_security(ticker)
            writes.setdefault("instrument_after", {})[ticker] = {
                "instrument_type": resolved.instrument_type,
                "source": resolved.source,
            }

    if args.enqueue:
        live_queue = UniverseExpansionRepository(raw)
        live_plan = plan_strategic_enqueue(
            enqueue_candidates,
            repo=live_queue,
            dry_run=False,
        )
        writes["enqueue"] = live_plan.to_dict()
        report["enqueue"] = live_plan.to_dict()

    if args.run_participation:
        live_queue = UniverseExpansionRepository(raw)
        eligible = [
            row
            for row in live_queue.list_all()
            if str(row.get("status") or "") in {"PENDING", "RETRYABLE"}
        ]
        extra = [
            str(row.get("symbol") or "").upper()
            for row in eligible
            if listing_identity(row.get("symbol")) not in set(pass_symbols)
        ]
        if extra:
            writes["participation"] = {
                "ran": False,
                "reason": "OTHER_ELIGIBLE_QUEUE_ROWS",
                "extra": extra,
            }
        elif not enqueue_candidates and not any(
            listing_identity(row.get("symbol")) in set(pass_symbols) for row in eligible
        ):
            writes["participation"] = {"ran": False, "reason": "NO_PENDING_PASS_SYMBOLS"}
        else:
            import os

            from services.fmp_client import FMPClient
            from services.sec_financial_client import SECFinancialClient

            fmp = FMPClient.from_env()
            sec = SECFinancialClient(contact_email=(os.environ.get("SEC_CONTACT_EMAIL") or "").strip())
            service = DailyUniverseExpansionService(queue_repo=live_queue)
            run = service.run_once(
                max_symbols=len(pass_symbols) or 8,
                dry_run=False,
                seed_if_empty=False,
                fmp_client=fmp,
                sec_client=sec,
                participation_repo=ParticipationAssessmentRepository(raw),
                candidate_repo=CandidateRepository(raw),
            )
            writes["participation"] = {
                "ran": True,
                "stop_reason": run.stop_reason,
                "symbols_started": run.symbols_started,
                "details": [item.to_dict() for item in run.symbol_details],
            }

    if args.scan_uygun:
        import os

        from services.fmp_client import FMPClient
        from services.participation_authority import resolve_authoritative_participation
        from services.scanner_v8_engine import ScannerV8Engine
        from services.sec_financial_client import SECFinancialClient

        live_queue = UniverseExpansionRepository(raw)
        live_candidates = CandidateRepository(raw)
        snapshots = ParticipationAssessmentRepository(raw).list_latest_by_symbol()
        fmp = FMPClient.from_env()
        sec = SECFinancialClient(contact_email=(os.environ.get("SEC_CONTACT_EMAIL") or "").strip())
        engine = ScannerV8Engine(fmp, sec)
        scan_report = {}
        for ticker in pass_symbols:
            qrow = live_queue.get_by_symbol(ticker) or {}
            if str(qrow.get("participation_status") or "").strip() != "Uygun":
                scan_report[ticker] = {"ran": False, "reason": "NOT_UYGUN"}
                continue
            existing = live_candidates.get_by_symbol(ticker)
            authority = resolve_authoritative_participation(
                ticker,
                candidate=existing,
                snapshot=snapshots.get(ticker),
            )
            if not authority.scanner_allowed:
                scan_report[ticker] = {
                    "ran": False,
                    "reason": authority.skip_reason or "SCANNER_NOT_ALLOWED",
                    "research_allowed": getattr(authority, "research_allowed", None),
                }
                continue
            result = engine.analyze(
                symbol=ticker,
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
            scan_report[ticker] = {
                "ran": True,
                "decision": candidate.get("decision_label") or candidate.get("decision"),
                "actionable": is_actionable_opportunity(candidate),
                "persisted": should_write,
                "completeness": candidate.get("data_completeness"),
                "excluded": result.get("excluded"),
            }
        writes["scan"] = scan_report

    refreshed_queue = UniverseExpansionRepository(readonly).list_all()
    refreshed_candidates = CandidateRepository(readonly).get_all(limit=5000) or []
    cand_map = {
        str(row.get("symbol") or "").strip().upper(): row for row in refreshed_candidates
    }
    qmap = {
        str(row.get("symbol") or "").strip().upper(): row for row in refreshed_queue
    }
    refreshed_master = production_security_master(readonly)
    refreshed_identity = identity_service_from_security_master(refreshed_master)
    matrix = {}
    eligible_fillers = []
    for ticker in US_REIT_ONBOARDING_TARGETS:
        plan_row = next((row for row in plan.rows if row.ticker == ticker), None)
        classification = _classification_status(plan_row) if plan_row else CLASSIFICATION_FAIL
        qrow = qmap.get(ticker) or {}
        participation = str(qrow.get("participation_status") or "") or "PENDING"
        if not qrow:
            participation = "NOT_RUN"
        crow = cand_map.get(ticker)
        actionability = actionability_from_candidate(crow)
        layer = refreshed_identity.resolve_economic_layer([ticker]).economic_layer
        if classification == CLASSIFICATION_PASS and layer != "real_estate":
            classification = CLASSIFICATION_FAIL
        gate = three_gate_eligibility(
            classification_status=classification,
            participation_status=str(qrow.get("participation_status") or ""),
            actionability=actionability,
            discovery_reason=REASON_ROBUST_UW_REAL_ESTATE,
        )
        if gate == "ELIGIBLE_FILLER":
            eligible_fillers.append(ticker)
        matrix[ticker] = {
            "classification": classification,
            "participation": participation,
            "research_allowed": qrow.get("research_allowed"),
            "actionability": actionability,
            "economic_layer": layer,
            "instrument_type": refreshed_master.resolve_security(ticker).instrument_type,
            "eligible_real_estate_filler": gate == "ELIGIBLE_FILLER",
        }
    report["writes"] = writes
    report["three_gate"] = matrix
    report["eligible_real_estate_fillers"] = eligible_fillers
    report["post_invariants"] = _invariants(readonly, refreshed_queue)
    user_id = _user_id(raw)
    bundle = _portfolio_bundle(raw, readonly, user_id)
    report["portfolio"] = bundle["summary"]
    report["new_money_off"] = _new_money(bundle, hybrid=False)
    if args.hybrid_uat or eligible_fillers:
        report["hybrid_uat"] = _new_money(bundle, hybrid=True)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
