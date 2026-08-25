"""Sprint C1 pilot: plan, fetch, and replay filing NPR for a small cohort.

No production participation writes. Symbol list is a sprint sample, not
per-issuer methodology. Fetch uses the existing SEC client only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from repositories.sec_company_facts_cache import SecCompanyFactsCache
from repositories.sec_filing_evidence_cache import SecFilingEvidenceCache
from services.participation_business_contract import BusinessActivityEvidence
from services.participation_cached_evidence_resolver import (
    _accession_from_payload,
    _period_from_financials,
)
from services.participation_filing_npr_resolver import (
    assess_with_filing_npr,
    resolve_npr_from_cached_filing,
)
from services.participation_inline_xbrl_attribution import fetch_primary_filing_html
from services.participation_sec_input_resolver import build_participation_inputs_from_sec
from services.participation_source_evidence import participation_source_evidence_mapping
from services.sec_company_facts_evidence import pad_cik
from services.sec_financial_client import SECFinancialClient
from services.sec_primary_filing_resolver import resolve_annual_filing_for_period

C1_PILOT_SYMBOLS = (
    "MSFT",
    "NVDA",
    "AMZN",
    "DE",
    "ABT",
    "GOOGL",
    "ACN",
    "WMT",
)

C1_PILOT_RATIONALE = {
    "MSFT": "software/cloud; B1 broad operating-segment partition",
    "NVDA": "semiconductor; B1 broad partition",
    "AMZN": "consumer/cloud; B1 broad partition",
    "DE": "industrial; B1 no explicit segment attribution",
    "ABT": "healthcare; B1 broad partition",
    "GOOGL": "digital advertising/platform; B1 broad partition",
    "ACN": "software services; B1 mapping-ambiguous",
    "WMT": "consumer; B1 missing attribution",
}

MAX_PLANNED_SEC_CALLS = 24
SEC_CALL_PAUSE_SECONDS = 0.25
APPROVED_ANCHORS = ("ADBE", "ADSK", "BIIB", "CRM", "JNJ", "MU")
REJECTED_SAMPLE = ("AAPL", "REGN", "VRSK")


@dataclass(frozen=True)
class PilotFetchPlanItem:
    symbol: str
    cik: Optional[str]
    canonical_period: Optional[str]
    canonical_revenue: Optional[float]
    preferred_accession: Optional[str]
    filing_cached: bool
    planned_sec_calls: int
    required_resource: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "cik": self.cik,
            "canonical_period": self.canonical_period,
            "canonical_revenue": self.canonical_revenue,
            "preferred_accession": self.preferred_accession,
            "filing_cached": self.filing_cached,
            "planned_sec_calls": self.planned_sec_calls,
            "required_resource": self.required_resource,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class PilotFetchPlan:
    items: tuple[PilotFetchPlanItem, ...]
    planned_sec_calls: int
    stop: bool
    stop_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "planned_sec_calls": self.planned_sec_calls,
            "stop": self.stop,
            "stop_reason": self.stop_reason,
        }


def _snapshot_cik(snapshot: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not snapshot:
        return None
    payload = snapshot.get("assessment_payload") or {}
    for source in (payload.get("source_evidence"), snapshot.get("source_evidence")):
        cik = participation_source_evidence_mapping(source).get("cik")
        if cik:
            return pad_cik(cik)
    return None


def _snapshot_business_evidence(
    symbol: str,
    snapshot: Optional[Mapping[str, Any]],
) -> BusinessActivityEvidence:
    payload = (snapshot or {}).get("assessment_payload") or {}
    src = participation_source_evidence_mapping(
        payload.get("source_evidence") or (snapshot or {}).get("source_evidence")
    )
    biz = payload.get("business_evidence") or {}
    if not isinstance(biz, Mapping):
        biz = {}
    return BusinessActivityEvidence(
        symbol=symbol,
        sic_code=str(biz.get("sic_code") or src.get("sic_code") or "") or None,
        sic_description=str(biz.get("sic_description") or src.get("sic_description") or "")
        or None,
        sector=str(biz.get("sector") or src.get("sector") or "") or None,
        industry=str(biz.get("industry") or src.get("industry") or "") or None,
        business_description=str(
            biz.get("business_description") or src.get("business_description") or ""
        )
        or None,
        source="snapshot",
    )


def plan_pilot_filing_fetch(
    *,
    symbols: Sequence[str] = C1_PILOT_SYMBOLS,
    snapshots_by_symbol: Mapping[str, Mapping[str, Any]],
    facts_cache: SecCompanyFactsCache,
    filing_cache: SecFilingEvidenceCache,
) -> PilotFetchPlan:
    items: list[PilotFetchPlanItem] = []
    planned = 0
    for symbol in symbols:
        snapshot = snapshots_by_symbol.get(symbol)
        cik = _snapshot_cik(snapshot)
        evidence = facts_cache.get_latest(symbol=symbol, cik=cik)
        period = None
        revenue = None
        accession = None
        if evidence is not None:
            extracted = facts_cache.replay(evidence)
            period = _period_from_financials(extracted)
            revenue = extracted.get("revenue")
            accession = _accession_from_payload(evidence.raw_payload, period)
        cached = filing_cache.get_latest(accession=accession) if accession else None
        if cached is None:
            cached = filing_cache.get_latest(symbol=symbol, cik=cik)
        calls = 0 if cached is not None else (2 if cik else 0)
        planned += calls
        items.append(
            PilotFetchPlanItem(
                symbol=symbol,
                cik=cik,
                canonical_period=period,
                canonical_revenue=float(revenue) if revenue is not None else None,
                preferred_accession=accession,
                filing_cached=cached is not None,
                planned_sec_calls=calls,
                required_resource=(
                    "cached_primary_filing"
                    if cached is not None
                    else "submissions+primary_10k_html"
                    if cik
                    else "missing_cik"
                ),
                rationale=C1_PILOT_RATIONALE.get(symbol, "evidence-diverse B1 NPR-blocked name"),
            )
        )
    stop = planned > MAX_PLANNED_SEC_CALLS
    return PilotFetchPlan(
        items=tuple(items),
        planned_sec_calls=planned,
        stop=stop,
        stop_reason="planned SEC call volume exceeds C1 pilot budget" if stop else "",
    )


def fetch_pilot_filings(
    plan: PilotFetchPlan,
    *,
    sec_client: SECFinancialClient,
    filing_cache: SecFilingEvidenceCache,
    pause_seconds: float = SEC_CALL_PAUSE_SECONDS,
) -> dict[str, Any]:
    if plan.stop:
        return {
            "stopped": True,
            "reason": plan.stop_reason,
            "sec_calls": 0,
            "successes": 0,
            "failures": 0,
            "objects": [],
        }
    objects: list[dict[str, Any]] = []
    successes = 0
    failures = 0
    sec_calls = 0
    for item in plan.items:
        if item.filing_cached or not item.cik:
            if item.filing_cached:
                cached = (
                    filing_cache.get_latest(accession=item.preferred_accession)
                    if item.preferred_accession
                    else None
                )
                if cached is None:
                    cached = filing_cache.get_latest(symbol=item.symbol, cik=item.cik)
                if cached is not None:
                    objects.append(
                        {
                            "symbol": item.symbol,
                            "digest": cached.content_digest,
                            "accession": cached.accession,
                            "created": False,
                        }
                    )
                    successes += 1
            continue
        try:
            submissions = sec_client.company_submissions(item.cik)
            sec_calls += 1
            time.sleep(pause_seconds)
            filing_ref = resolve_annual_filing_for_period(
                submissions,
                cik=item.cik,
                preferred_period_end=item.canonical_period,
                preferred_accession=item.preferred_accession,
            )
            if filing_ref is None:
                failures += 1
                objects.append({"symbol": item.symbol, "error": "no_annual_filing"})
                continue
            raw = fetch_primary_filing_html(sec_client, filing_ref)
            sec_calls += 1
            time.sleep(pause_seconds)
            evidence, created = filing_cache.store_if_new(
                symbol=item.symbol,
                cik=item.cik,
                accession=filing_ref.accession_number,
                form=filing_ref.form,
                filing_date=filing_ref.filing_date,
                primary_document=filing_ref.primary_document,
                raw_bytes=raw,
                fiscal_year=filing_ref.fiscal_year,
            )
            filing_cache.verify_digest(evidence.content_digest)
            objects.append(
                {
                    "symbol": item.symbol,
                    "digest": evidence.content_digest,
                    "accession": evidence.accession,
                    "form": evidence.form,
                    "filing_date": evidence.filing_date,
                    "primary_document": evidence.primary_document,
                    "bytes": len(evidence.raw_bytes),
                    "created": created,
                }
            )
            successes += 1
        except Exception as exc:
            failures += 1
            objects.append({"symbol": item.symbol, "error": exc.__class__.__name__})
    return {
        "stopped": False,
        "sec_calls": sec_calls,
        "successes": successes,
        "failures": failures,
        "objects": objects,
        "fmp_calls": 0,
        "llm_calls": 0,
    }


def replay_pilot_from_cache(
    plan: PilotFetchPlan,
    *,
    snapshots_by_symbol: Mapping[str, Mapping[str, Any]],
    facts_cache: SecCompanyFactsCache,
    filing_cache: SecFilingEvidenceCache,
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for item in plan.items:
        snapshot = snapshots_by_symbol.get(item.symbol) or {}
        filing = (
            filing_cache.get_latest(accession=item.preferred_accession)
            if item.preferred_accession
            else None
        )
        if filing is None:
            filing = filing_cache.get_latest(symbol=item.symbol, cik=item.cik)
        if filing is None:
            rows.append(
                {
                    "symbol": item.symbol,
                    "raw_filing_available": False,
                    "parser_success": False,
                    "classification": "FILING_HAS_NO_USABLE_ATTRIBUTION",
                    "participation_before": snapshot.get("status"),
                    "participation_after": snapshot.get("status"),
                }
            )
            continue
        filing_cache.verify_digest(filing.content_digest)
        resolution = resolve_npr_from_cached_filing(
            filing,
            canonical_period=item.canonical_period,
            canonical_revenue=item.canonical_revenue,
        )
        facts = facts_cache.get_latest(symbol=item.symbol, cik=item.cik)
        extracted = facts_cache.replay(facts) if facts is not None else {}
        inputs = build_participation_inputs_from_sec(
            item.symbol,
            extracted,
            cik=item.cik,
        ).inputs
        assessed = assess_with_filing_npr(
            symbol=item.symbol,
            financial_inputs=inputs,
            business_evidence=_snapshot_business_evidence(item.symbol, snapshot),
            filing_resolution=resolution,
        )
        rows.append(
            {
                **resolution.to_dict(),
                "raw_filing_available": True,
                "participation_before": snapshot.get("status"),
                "participation_after": assessed["status"],
                "financial_outcome": assessed["financial"],
                "business_outcome": assessed["business"],
                "missing": assessed["missing"],
            }
        )
    return tuple(rows)
