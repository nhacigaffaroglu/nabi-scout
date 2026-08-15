#!/usr/bin/env python3
"""Run the real CRM Company Report valuation path and print a redacted trace."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("NABI_AI_SUMMARY_TRACE", "1")

from supabase import create_client

from repositories.candidate_repository import CandidateRepository
from services.ai_research_summary_prompt import build_ai_summary_payload
from services.ai_research_summary_service import (
    AIResearchSummaryService,
    compute_evidence_level,
    infer_financial_trends_source,
)
from services.ai_research_summary_trace import get_last_ai_summary_generation_trace
from services.ai_research_summary_valuation_semantics import derive_valuation_semantics
from services.company_intelligence_core_service import CompanyIntelligenceCoreService
from services.company_intelligence_sec_valuation import resolve_hybrid_market_cap
from services.company_report_participation_service import build_company_report_participation
from services.fmp_client import FMPClient, FMPError
from services.investment_thesis_service import InvestmentThesisService
from services.research_eligibility_service import evaluate_research_eligibility_from_participation_view
from services.sec_financial_client import SECFinancialClient
from services.sec_contact_config import get_sec_contact_email
from services.unified_research_service import UnifiedResearchService
from services.wealth_adviser_config import load_adviser_llm_config


def _load_secrets() -> dict:
    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    with secrets_path.open("rb") as handle:
        return tomllib.load(handle)


def _authenticated_supabase(secrets: dict):
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


def _metric_summary(view) -> list[dict]:
    if view.valuation is None:
        return []
    return [
        {
            "code": metric.code,
            "label": metric.label,
            "current_value": metric.current_value,
        }
        for metric in view.valuation.metrics
    ]


def _profile_status(fmp: FMPClient, symbol: str) -> dict:
    try:
        profile = fmp.profile(symbol)
        market_cap = profile.get("marketCap") or profile.get("mktCap")
        return {
            "status": "OK",
            "error_class": None,
            "market_cap": market_cap,
            "company_name": profile.get("companyName") or profile.get("company_name"),
        }
    except FMPError as exc:
        return {
            "status": "ERROR",
            "error_class": exc.error_class,
            "market_cap": None,
            "company_name": None,
        }


def main() -> int:
    secrets = _load_secrets()
    os.environ.setdefault("NABI_AI_SUMMARY_TRACE", "1")
    sec_contact = str(secrets.get("sec", {}).get("contact_email") or "").strip()
    if sec_contact:
        os.environ.setdefault("SEC_CONTACT_EMAIL", sec_contact)
    wealth = secrets.get("wealth_adviser") or {}
    if wealth.get("api_key"):
        os.environ.setdefault("WEALTH_ADVISER_LLM_API_KEY", str(wealth["api_key"]).strip())
    if wealth.get("enabled") is not None:
        os.environ.setdefault("WEALTH_ADVISER_LLM_ENABLED", str(wealth["enabled"]).strip())
    supabase = _authenticated_supabase(secrets)
    fmp = FMPClient(str(secrets["fmp"]["api_key"]).strip())
    llm_config = load_adviser_llm_config()

    repo = CandidateRepository(supabase)
    candidate = repo.get_by_symbol("CRM")
    if candidate is None:
        print("FAIL: CRM candidate not found in database")
        return 1

    candidate_market_cap = candidate.get("market_cap")
    print("=== CRM LIVE VALUATION VERIFICATION ===")
    print(f"candidate.market_cap: {candidate_market_cap}")

    profile_probe = _profile_status(fmp, "CRM")
    print(f"fmp.profile.status: {profile_probe['status']}")
    print(f"fmp.profile.error_class: {profile_probe['error_class']}")
    print(f"fmp.profile.market_cap: {profile_probe['market_cap']}")

    sec_email = get_sec_contact_email() or secrets.get("sec", {}).get("contact_email")
    sec_client = SECFinancialClient(contact_email=str(sec_email or "").strip())

    participation_fmp = FMPClient(str(secrets["fmp"]["api_key"]).strip())
    participation_view = build_company_report_participation(
        candidate,
        sec_client=sec_client,
        fmp_client=participation_fmp,
        persistence_available=False,
        sec_ticker_lookup={"CRM": {"symbol": "CRM", "cik": "1108524", "company_name": "Salesforce, Inc."}},
    )
    research_eligibility = evaluate_research_eligibility_from_participation_view(participation_view)
    if not research_eligibility.research_allowed:
        print(f"FAIL: research not allowed: {research_eligibility.reason_codes}")
        return 1

    sec_financials = (
        participation_view.result.sec_financials
        if participation_view.result is not None
        else None
    )
    ci_service = CompanyIntelligenceCoreService(fmp)
    company_intel_view = ci_service.build_view(
        "CRM",
        research_eligibility=research_eligibility,
        sec_financials=sec_financials,
        market_cap_fallback=candidate.get("market_cap"),
    )

    bundle = ci_service.load_bundle(
        "CRM",
        research_eligibility=research_eligibility,
        sec_financials=sec_financials,
        market_cap_fallback=candidate.get("market_cap"),
    )
    selected_market_cap = resolve_hybrid_market_cap(bundle)
    profile_market_cap = (bundle.profile or {}).get("marketCap") or (bundle.profile or {}).get("mktCap")
    fallback_used = (
        selected_market_cap is not None
        and (profile_market_cap in (None, "", 0))
        and candidate_market_cap is not None
        and float(candidate_market_cap) == float(selected_market_cap)
    )

    print(f"profile:RATE_LIMIT in provider_failures: {'profile:RATE_LIMIT' in (company_intel_view.data_quality.provider_failures if company_intel_view.data_quality else ())}")
    print(f"fallback_used: {fallback_used}")
    print(f"selected_market_cap: {selected_market_cap}")
    print(f"company_intel_view.valuation_metrics: {json.dumps(_metric_summary(company_intel_view), ensure_ascii=False)}")
    print(f"data_quality.valuation_available: {company_intel_view.data_quality.valuation_available if company_intel_view.data_quality else None}")

    investment_thesis_view = InvestmentThesisService().build_view(
        company_intel_view,
        research_eligibility=research_eligibility,
        candidate=candidate,
    )
    unified = UnifiedResearchService().build_context(
        symbol="CRM",
        research_eligibility=research_eligibility,
        company_intelligence_view=company_intel_view,
        investment_thesis_view=investment_thesis_view,
        candidate=candidate,
        participation_view=participation_view,
    )
    semantics = derive_valuation_semantics(unified)
    evidence_level = compute_evidence_level(unified, investment_thesis_view=investment_thesis_view)
    payload = build_ai_summary_payload(
        unified,
        evidence_level=evidence_level,
        financial_trends_source=infer_financial_trends_source(company_intel_view),
    )

    ci = unified.company_intelligence or {}
    prompt_slice = {
        "valuation_semantics": payload["authoritative_constraints"]["valuation_semantics"],
        "coverage": payload["authoritative_constraints"]["coverage"],
        "valuation_metrics": ci.get("valuation_metrics"),
    }
    print(f"UnifiedResearchContext.valuation_metrics: {json.dumps(ci.get('valuation_metrics') or [], ensure_ascii=False)}")
    print(f"valuation_semantics.current_valuation_metrics_available: {semantics.current_metrics_available}")
    print(f"valuation_semantics.available_valuation_metrics: {json.dumps(list(semantics.available_metrics), ensure_ascii=False)}")
    print(f"prompt valuation slice: {json.dumps(prompt_slice, ensure_ascii=False)}")

    if not llm_config.is_usable:
        print("LLM not usable in this environment; stopping before generate()")
        return 0

    service = AIResearchSummaryService(config=llm_config)
    view = service.generate(
        symbol="CRM",
        research_eligibility=research_eligibility,
        company_intelligence_view=company_intel_view,
        investment_thesis_view=investment_thesis_view,
        candidate=candidate,
        participation_view=participation_view,
        force_refresh=True,
    )
    trace = get_last_ai_summary_generation_trace() or {}
    print(f"generate.status: {view.status}")
    if view.metadata:
        print(f"generate.validation_outcome: {view.metadata.validation_outcome}")
    print(f"raw_llm_valuation_summary: {trace.get('raw_llm_valuation_summary')}")
    print(f"parsed_valuation_summary: {trace.get('parsed_valuation_summary')}")
    print(f"final_valuation_summary: {trace.get('final_valuation_summary') or view.valuation_summary}")
    if view.status == "AVAILABLE":
        hesap = "hesaplanam" in (view.valuation_summary or "").lower()
        has_metrics = any(
            label in (view.valuation_summary or "")
            for label in ("P/S", "Fiyat/Satış", "3.86", "3.87", "hibrit")
        )
        print(f"final_acknowledges_metrics: {has_metrics and not hesap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
