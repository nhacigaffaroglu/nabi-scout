#!/usr/bin/env python3
"""Live verification harness for AI Research Summary persistence (safe diagnostics only)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from repositories.ai_research_summary_repository import AIResearchSummaryRepository
from repositories.candidate_repository import CandidateRepository
from services.ai_research_summary_display import polish_ai_research_summary_view
from services.ai_research_summary_persistence_service import (
    audit_persisted_summary_payload,
    fetch_exact_ai_research_summary,
    save_ai_research_summary_snapshot,
    symbol_has_stale_persisted_summary,
    view_from_row,
)
from services.ai_research_summary_service import (
    AIResearchSummaryService,
    compute_context_semantic_identity,
)
from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.company_report_participation_service import build_company_report_participation
from services.fmp_client import FMPClient
from services.investment_thesis_service import InvestmentThesisService
from services.research_eligibility_service import (
    evaluate_research_eligibility_from_participation_view,
)
from services.sec_financial_client import SECFinancialClient
from services.sec_contact_config import get_sec_contact_email
from services.wealth_adviser_config import load_adviser_llm_config


@dataclass
class LlmCallCounter:
    count: int = 0

    def complete(self, *args, **kwargs):
        self.count += 1
        raise RuntimeError("LLM should not be called during persistence reload verification")


@dataclass
class VerificationReport:
    migration_table: str = "ai_research_summary_snapshots"
    persisted_row_found: bool = False
    identity_a: str = ""
    rows: List[Dict[str, Any]] = field(default_factory=list)
    payload_audit: Dict[str, Any] = field(default_factory=dict)
    same_session: Dict[str, Any] = field(default_factory=dict)
    fresh_session: Dict[str, Any] = field(default_factory=dict)
    restart_simulation: Dict[str, Any] = field(default_factory=dict)
    row_count_before: int = 0
    row_count_after: int = 0
    get_or_create: Dict[str, Any] = field(default_factory=dict)
    stale_context: Dict[str, Any] = field(default_factory=dict)
    timestamp_stability: Dict[str, Any] = field(default_factory=dict)
    validation_failed_rows: List[Dict[str, Any]] = field(default_factory=list)
    firewall: Dict[str, Any] = field(default_factory=dict)
    field_separation: Dict[str, Any] = field(default_factory=dict)


def _load_secrets() -> dict:
    with (ROOT / ".streamlit" / "secrets.toml").open("rb") as handle:
        return tomllib.load(handle)


def _authenticated_supabase(secrets: dict):
    from supabase import create_client

    client = create_client(
        str(secrets["supabase"]["url"]).strip(),
        str(secrets["supabase"]["publishable_key"]).strip(),
    )
    dev_auth = secrets.get("dev_auth") or {}
    enabled = str(dev_auth.get("enabled") or "").strip().lower() in {"1", "true", "yes", "on"}
    email = str(dev_auth.get("email") or "").strip()
    password = str(dev_auth.get("password") or "").strip()
    if enabled and email and password:
        session = client.auth.sign_in_with_password(
            {"email": email, "password": password}
        ).session
        client.postgrest.auth(session.access_token)
    return client


def _row_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "semantic_identity": row.get("semantic_identity"),
        "source_context_version": row.get("source_context_version"),
        "summary_version": row.get("summary_version"),
        "display_version": row.get("display_version"),
        "validation_version": row.get("validation_version"),
        "status": row.get("status"),
        "evidence_level": row.get("evidence_level"),
        "model_provider": row.get("model_provider"),
        "model_name": row.get("model_name"),
        "generated_at": row.get("generated_at"),
        "created_at": row.get("created_at"),
    }


def _build_crm_context(supabase, secrets):
    sec_contact = str(secrets.get("sec", {}).get("contact_email") or "").strip()
    if sec_contact:
        os.environ.setdefault("SEC_CONTACT_EMAIL", sec_contact)
    fmp = FMPClient(str(secrets["fmp"]["api_key"]).strip())
    candidate = CandidateRepository(supabase).get_by_symbol("CRM")
    if candidate is None:
        raise RuntimeError("CRM candidate not found")
    sec_email = get_sec_contact_email() or sec_contact
    sec_client = SECFinancialClient(contact_email=str(sec_email or "").strip())
    participation_view = build_company_report_participation(
        candidate,
        sec_client=sec_client,
        fmp_client=FMPClient(str(secrets["fmp"]["api_key"]).strip()),
        persistence_available=False,
        sec_ticker_lookup={
            "CRM": {"symbol": "CRM", "cik": "1108524", "company_name": "Salesforce, Inc."}
        },
    )
    research_eligibility = evaluate_research_eligibility_from_participation_view(participation_view)
    sec_financials = (
        participation_view.result.sec_financials if participation_view.result else None
    )
    ci_service = CompanyIntelligenceCoreService(fmp)
    company_intel_view = ci_service.build_view(
        "CRM",
        research_eligibility=research_eligibility,
        sec_financials=sec_financials,
        market_cap_fallback=candidate.get("market_cap"),
    )
    investment_thesis_view = InvestmentThesisService().build_view(
        company_intel_view,
        research_eligibility=research_eligibility,
        candidate=candidate,
    )
    identity = compute_context_semantic_identity(
        symbol="CRM",
        participation_result=(
            participation_view.result if participation_view.result is not None else None
        ),
        company_intelligence_view=company_intel_view,
        investment_thesis_view=investment_thesis_view,
    )
    return {
        "candidate": candidate,
        "participation_view": participation_view,
        "research_eligibility": research_eligibility,
        "company_intel_view": company_intel_view,
        "investment_thesis_view": investment_thesis_view,
        "identity": identity,
    }


def _audit_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = row.get("summary_payload") or {}
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden_hits = [
        token
        for token in (
            "api_key",
            "authorization",
            "bearer ",
            "raw prompt",
            "raw_llm",
            "secret",
            "password",
        )
        if token in serialized
    ]
    audit_ok = True
    audit_error = None
    try:
        audit_persisted_summary_payload(payload)
    except ValueError as exc:
        audit_ok = False
        audit_error = str(exc)

    valuation = str(payload.get("valuation_summary") or "")
    fields = {
        "financial_outlook": payload.get("financial_outlook"),
        "valuation_summary": valuation[:160],
        "key_strengths": payload.get("key_strengths"),
        "key_weaknesses": payload.get("key_weaknesses"),
        "missing_evidence": payload.get("missing_evidence"),
        "monitoring_points": payload.get("monitoring_points"),
        "limitations": payload.get("limitations"),
        "evidence_level": payload.get("evidence_level"),
    }
    valuation_lower = valuation.lower()
    duplicated = []
    for name, value in fields.items():
        if name == "valuation_summary" or not value:
            continue
        texts = value if isinstance(value, list) else [value]
        for text in texts:
            if isinstance(text, str) and valuation_lower and text.lower() == valuation_lower:
                duplicated.append(name)
    return {
        "audit_ok": audit_ok,
        "audit_error": audit_error,
        "forbidden_hits": forbidden_hits,
        "has_hybrid_metrics": any(token in valuation for token in ("3.87", "11.16", "20.14", "P/S", "Fiyat/Satış")),
        "field_duplication_of_valuation": duplicated,
        "field_keys_present": sorted(payload.keys()),
    }


def _simulate_page_load(*, ctx, repo, session_cache: Optional[dict], llm_counter: LlmCallCounter):
    identity = ctx["identity"]
    db_lookups = 0
    source = None
    view = None

    if session_cache and session_cache.get("identity") == identity:
        view = session_cache.get("view")
        source = "SESSION_CACHE"
    else:
        db_lookups += 1
        exact = fetch_exact_ai_research_summary(repo, "CRM", identity)
        if exact.view is not None:
            service = AIResearchSummaryService(config=load_adviser_llm_config(), client=MagicMock())
            unified = service.build_unified_context(
                symbol="CRM",
                research_eligibility=ctx["research_eligibility"],
                company_intelligence_view=ctx["company_intel_view"],
                investment_thesis_view=ctx["investment_thesis_view"],
                candidate=ctx["candidate"],
                participation_view=ctx["participation_view"],
            )
            view = polish_ai_research_summary_view(exact.view, unified=unified)
            source = "PERSISTED_DB"

    # Defensive: generate must not be needed on load
    if view is None:
        service = AIResearchSummaryService(
            config=load_adviser_llm_config(),
            client=llm_counter,  # type: ignore[arg-type]
        )
        service.generate(
            symbol="CRM",
            research_eligibility=ctx["research_eligibility"],
            company_intelligence_view=ctx["company_intel_view"],
            investment_thesis_view=ctx["investment_thesis_view"],
            candidate=ctx["candidate"],
            participation_view=ctx["participation_view"],
            force_refresh=False,
        )

    return {
        "semantic_identity": identity,
        "source": source,
        "db_lookups": db_lookups,
        "session_cache_hit": source == "SESSION_CACHE",
        "persisted_lookup_hit": source == "PERSISTED_DB",
        "ai_summary_llm_calls": llm_counter.count,
        "view_status": view.status if view else None,
        "validation_outcome": (
            view.metadata.validation_outcome if view and view.metadata else None
        ),
        "view": view,
    }


def main() -> int:
    secrets = _load_secrets()
    supabase = _authenticated_supabase(secrets)
    ctx = _build_crm_context(supabase, secrets)
    repo = AIResearchSummaryRepository(supabase)
    report = VerificationReport(identity_a=ctx["identity"])

    all_rows = repo.get_recent_history("CRM", limit=25)
    report.rows = [_row_summary(row) for row in all_rows]
    exact_row = repo.get_exact("CRM", ctx["identity"])
    report.persisted_row_found = exact_row is not None and exact_row.get("status") == "AVAILABLE"
    report.row_count_before = len(repo.get_recent_history("CRM", limit=100))

    if exact_row:
        report.payload_audit = _audit_payload(exact_row)
        view = view_from_row(exact_row, semantic_identity=ctx["identity"])
        valuation = view.valuation_summary or ""
        strengths = view.key_strengths or ()
        report.field_separation = {
            "valuation_distinct_from_strengths": all(
                (s or "").lower() != valuation.lower() for s in strengths
            ),
            "valuation_has_metrics": any(x in valuation for x in ("3.87", "P/S", "Fiyat/Satış")),
            "strength_sample": strengths[0] if strengths else None,
            "financial_outlook_sample": (view.financial_outlook or "")[:120],
        }

    llm_counter = LlmCallCounter()

    # Same-session: seeded cache
    cached_view = view_from_row(exact_row, semantic_identity=ctx["identity"]) if exact_row else None
    session_cache = (
        {"identity": ctx["identity"], "view": cached_view} if cached_view else None
    )
    report.same_session = _simulate_page_load(
        ctx=ctx, repo=repo, session_cache=session_cache, llm_counter=llm_counter
    )

    # Fresh session: empty cache (critical acceptance)
    fresh_counter = LlmCallCounter()
    report.fresh_session = _simulate_page_load(
        ctx=ctx, repo=repo, session_cache=None, llm_counter=fresh_counter
    )

    # Restart simulation = fresh session again, record row id stability
    restart_counter = LlmCallCounter()
    report.restart_simulation = _simulate_page_load(
        ctx=ctx, repo=repo, session_cache=None, llm_counter=restart_counter
    )
    if exact_row:
        report.restart_simulation["persisted_row_id"] = exact_row.get("id")
        report.restart_simulation["generated_at"] = exact_row.get("generated_at")

    report.row_count_after = len(
        [row for row in repo.get_recent_history("CRM", limit=100) if row.get("semantic_identity") == ctx["identity"]]
    )

    # Get-or-create via service with DB pre-check (mirrors page button path)
    goc_counter = LlmCallCounter()
    goc_service = AIResearchSummaryService(
        config=load_adviser_llm_config(),
        client=goc_counter,  # type: ignore[arg-type]
    )
    pre = fetch_exact_ai_research_summary(repo, "CRM", ctx["identity"])
    reused = None
    if pre.view is not None:
        reused = pre.view
        goc_llm = 0
    else:
        goc_service.generate(
            symbol="CRM",
            research_eligibility=ctx["research_eligibility"],
            company_intelligence_view=ctx["company_intel_view"],
            investment_thesis_view=ctx["investment_thesis_view"],
            candidate=ctx["candidate"],
            participation_view=ctx["participation_view"],
            force_refresh=False,
        )
        goc_llm = goc_counter.count
    report.get_or_create = {
        "db_precheck_hit": pre.view is not None,
        "reused_status": reused.status if reused else None,
        "ai_summary_llm_calls": goc_llm,
    }

    # Stale context: old display version identity should miss
    from services import ai_research_summary_service as svc_mod
    from unittest.mock import patch

    with patch.object(svc_mod, "AI_RESEARCH_SUMMARY_DISPLAY_VERSION", "display-polish-v2"):
        identity_b_old = compute_context_semantic_identity(
            symbol="CRM",
            participation_result=(
                ctx["participation_view"].result
                if ctx["participation_view"].result is not None
                else None
            ),
            company_intelligence_view=ctx["company_intel_view"],
            investment_thesis_view=ctx["investment_thesis_view"],
        )
    miss = fetch_exact_ai_research_summary(repo, "CRM", identity_b_old)
    report.stale_context = {
        "identity_a": ctx["identity"],
        "identity_b_simulated": identity_b_old,
        "identities_differ": identity_b_old != ctx["identity"],
        "exact_lookup_b_hit": miss.view is not None,
        "stale_hint": symbol_has_stale_persisted_summary(repo, "CRM", ctx["identity"]),
        "history_count": len(all_rows),
    }

    # Timestamp stability via as_of-only CI change
    from services.company_intelligence_contract import CompanyIntelligenceView

    ci = ctx["company_intel_view"]
    ci2 = CompanyIntelligenceView(**{**ci.__dict__, "as_of": "2099-01-01T00:00:00Z"})
    id1 = compute_context_semantic_identity(
        symbol="CRM",
        participation_result=(
            ctx["participation_view"].result if ctx["participation_view"].result else None
        ),
        company_intelligence_view=ci,
        investment_thesis_view=ctx["investment_thesis_view"],
    )
    id2 = compute_context_semantic_identity(
        symbol="CRM",
        participation_result=(
            ctx["participation_view"].result if ctx["participation_view"].result else None
        ),
        company_intelligence_view=ci2,
        investment_thesis_view=ctx["investment_thesis_view"],
    )
    report.timestamp_stability = {"identity_as_of_a": id1, "identity_as_of_b": id2, "stable": id1 == id2}

    report.validation_failed_rows = [
        _row_summary(row)
        for row in all_rows
        if row.get("status") != "AVAILABLE"
    ]

    # Firewall: blocked symbol should not load persisted summary through service
    from services.research_eligibility_contract import RESEARCH_STATUS_FAIL, ResearchEligibilityResult

    blocked = ResearchEligibilityResult(
        symbol="AAPL",
        status=RESEARCH_STATUS_FAIL,
        research_allowed=False,
        participation_status="Uygun Değil",
        reason_codes=("blocked",),
        limitations=(),
        provenance=(),
    )
    fw_counter = LlmCallCounter()
    fw_service = AIResearchSummaryService(config=load_adviser_llm_config(), client=fw_counter)  # type: ignore[arg-type]
    fw_view = fw_service.generate(
        symbol="AAPL",
        research_eligibility=blocked,
        company_intelligence_view=ctx["company_intel_view"],
        investment_thesis_view=ctx["investment_thesis_view"],
    )
    report.firewall = {
        "status": fw_view.status,
        "ai_summary_llm_calls": fw_counter.count,
        "research_allowed": blocked.research_allowed,
    }

    # Safe trace summary
    trace = {
        "semantic_identity": ctx["identity"],
        "persisted_row_found": report.persisted_row_found,
        "fresh_session_cache_hit": report.fresh_session.get("session_cache_hit"),
        "fresh_session_persisted_hit": report.fresh_session.get("persisted_lookup_hit"),
        "fresh_session_llm_calls": report.fresh_session.get("ai_summary_llm_calls"),
        "row_count_identity_a": report.row_count_after,
    }
    report.restart_simulation["safe_trace"] = trace

    print(json.dumps(
        {
            "migration_table": report.migration_table,
            "persisted_row_found": report.persisted_row_found,
            "identity_a": report.identity_a,
            "exact_row": _row_summary(exact_row) if exact_row else None,
            "history_rows": report.rows,
            "payload_audit": report.payload_audit,
            "same_session": {k: v for k, v in report.same_session.items() if k != "view"},
            "fresh_session": {k: v for k, v in report.fresh_session.items() if k != "view"},
            "restart_simulation": {k: v for k, v in report.restart_simulation.items() if k != "view"},
            "row_count_before_identity_a": report.row_count_before,
            "row_count_for_identity_a": report.row_count_after,
            "field_separation": report.field_separation,
            "get_or_create": report.get_or_create,
            "stale_context": report.stale_context,
            "timestamp_stability": report.timestamp_stability,
            "validation_failed_rows": report.validation_failed_rows,
            "firewall": report.firewall,
            "safe_trace": trace,
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
