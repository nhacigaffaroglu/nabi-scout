"""Offline business/NPR evidence resolver for cached SEC Company Facts.

Reuses the canonical business classifier and NPR/safe-zero contract.
Does not call providers or an LLM. Missing NPR is never coerced to zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.participation_business_contract import (
    BusinessActivityEvidence,
    BusinessActivityScreenResult,
)
from services.participation_business_engine import evaluate_business_activity
from services.participation_business_evidence_enrichment import (
    derive_non_permissible_revenue_amount,
    enrich_business_activity_evidence,
)
from services.participation_methodology_capabilities import (
    CAPABILITY_PROHIBITED_REVENUE,
    blocking_missing_capabilities,
)
from services.participation_methodology_registry import get_default_equity_methodology_id
from services.participation_revenue_attribution_contract import (
    ATTRIBUTION_SUCCESS,
    MAPPING_AMBIGUOUS,
)
from services.participation_revenue_granularity import (
    LIMITATION_BROAD_PARTITION,
    LIMITATION_MATERIAL_OTHER,
    can_conclude_zero_prohibited_revenue,
)
from services.participation_sec_input_resolver import build_participation_inputs_from_sec
from services.participation_sec_segment_resolver import (
    extract_revenue_segments_from_sec,
    revenue_segments_to_business_evidence,
)
from services.sec_company_facts_evidence import SOURCE_SEC_COMPANY_FACTS
from services.sec_financial_client import SECFinancialClient

NPR_STATE_PROVEN_ZERO = "PROVEN_ZERO"
NPR_STATE_POSITIVE = "POSITIVE"
NPR_STATE_MISSING = "MISSING"
NPR_STATE_INSUFFICIENT = "INSUFFICIENT"

REASON_MISSING_PROHIBITED_REVENUE = f"missing_capability:{CAPABILITY_PROHIBITED_REVENUE}"
REASON_FINANCIAL_NPR_INSUFFICIENT = "financial_rule_insufficient:msci.non_permissible_revenue"
REASON_BUSINESS_NPR_INSUFFICIENT = "business_rule_insufficient:msci.non_permissible_revenue"
REASON_BUSINESS_SIC_INSUFFICIENT = "business_rule_insufficient:msci.sic_exclusions"
REASON_BUSINESS_SECTOR_INSUFFICIENT = "business_rule_insufficient:msci.sector_exclusions"
REASON_BUSINESS_SIC_REVIEW = "business_rule_review_required:msci.sic_exclusions"
REASON_BUSINESS_SECTOR_REVIEW = "business_rule_review_required:msci.sector_exclusions"

LIMITATION_EXPLICIT_SEGMENT_REQUIRED = (
    "Explicit revenue segment evidence not provided; "
    "coverage attestation cannot substitute for MSCI revenue attribution."
)
LIMITATION_NO_PROHIBITED_SEGMENT_EVIDENCE = (
    "Yasaklı gelir segment kanıtı sağlanmadı; "
    "MSCI metodolojisi açık gelir atfı gerektirir."
)
LIMITATION_MAPPING_AMBIGUOUS = "One or more revenue categories are ambiguous under MSCI taxonomy."
LIMITATION_MISSING_DENOMINATOR = "Missing consolidated revenue denominator."
LIMITATION_MISSING_TOTAL_REVENUE = (
    "Toplam gelir kanıtı olmadan yasaklı gelir tutarı türetilmedi."
)
LIMITATION_COMPANY_FACTS_NO_DIMENSIONAL_SEGMENTS = (
    "SEC Company Facts cached payload has no dimensional revenue members; "
    "Company Facts cannot prove non-permissible revenue."
)

RAW_STATUS = "raw"
DERIVED_STATUS = "derived"


@dataclass(frozen=True)
class EvidenceProvenance:
    source_type: str
    source_identifier: str
    period: Optional[str] = None
    filing_accession: Optional[str] = None
    field: Optional[str] = None
    concept: Optional[str] = None
    raw_or_derived: str = DERIVED_STATUS
    resolution_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_identifier": self.source_identifier,
            "period": self.period,
            "filing_accession": self.filing_accession,
            "field": self.field,
            "concept": self.concept,
            "raw_or_derived": self.raw_or_derived,
            "resolution_reason": self.resolution_reason,
        }


@dataclass(frozen=True)
class CachedBusinessNprResolution:
    symbol: str
    npr_amount: Optional[float]
    npr_state: str
    unresolved_reasons: Tuple[str, ...]
    limitations: Tuple[str, ...]
    company_facts_can_answer_npr: bool
    company_facts_can_answer_sic: bool
    company_facts_can_answer_description: bool
    period: Optional[str]
    currency: Optional[str]
    business_evidence: BusinessActivityEvidence
    business_screen: Optional[BusinessActivityScreenResult]
    provenance: Tuple[EvidenceProvenance, ...] = field(default_factory=tuple)
    missing_capabilities: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "npr_amount": self.npr_amount,
            "npr_state": self.npr_state,
            "unresolved_reasons": list(self.unresolved_reasons),
            "limitations": list(self.limitations),
            "company_facts_can_answer_npr": self.company_facts_can_answer_npr,
            "company_facts_can_answer_sic": self.company_facts_can_answer_sic,
            "company_facts_can_answer_description": self.company_facts_can_answer_description,
            "period": self.period,
            "currency": self.currency,
            "missing_capabilities": list(self.missing_capabilities),
            "provenance": [item.to_dict() for item in self.provenance],
        }


def npr_state_from_amount(
    amount: Optional[float],
    *,
    proven_zero: bool = False,
) -> str:
    if amount is None:
        return NPR_STATE_MISSING if not proven_zero else NPR_STATE_INSUFFICIENT
    if float(amount) > 0:
        return NPR_STATE_POSITIVE
    if proven_zero:
        return NPR_STATE_PROVEN_ZERO
    return NPR_STATE_INSUFFICIENT


def classify_npr_limitations(messages: Sequence[str]) -> Tuple[str, ...]:
    known = (
        LIMITATION_BROAD_PARTITION,
        LIMITATION_MATERIAL_OTHER,
        LIMITATION_EXPLICIT_SEGMENT_REQUIRED,
        LIMITATION_NO_PROHIBITED_SEGMENT_EVIDENCE,
        LIMITATION_MAPPING_AMBIGUOUS,
        LIMITATION_MISSING_DENOMINATOR,
        LIMITATION_MISSING_TOTAL_REVENUE,
        LIMITATION_COMPANY_FACTS_NO_DIMENSIONAL_SEGMENTS,
    )
    found: list[str] = []
    blob = " | ".join(str(item) for item in messages if item)
    for item in known:
        if item in blob and item not in found:
            found.append(item)
    return tuple(found)


def classify_unresolved_npr_reasons(
    *,
    npr_amount: Optional[float],
    missing_capabilities: Sequence[str] = (),
    financial_npr_outcome: Optional[str] = None,
    business_npr_outcome: Optional[str] = None,
    business_sic_outcome: Optional[str] = None,
    business_sector_outcome: Optional[str] = None,
    limitations: Sequence[str] = (),
) -> Tuple[str, ...]:
    reasons: list[str] = []
    if npr_amount is None and CAPABILITY_PROHIBITED_REVENUE in missing_capabilities:
        reasons.append(REASON_MISSING_PROHIBITED_REVENUE)
    if npr_amount is None and financial_npr_outcome == "INSUFFICIENT_DATA":
        reasons.append(REASON_FINANCIAL_NPR_INSUFFICIENT)
    if npr_amount is None and business_npr_outcome == "INSUFFICIENT_DATA":
        reasons.append(REASON_BUSINESS_NPR_INSUFFICIENT)
    if business_sic_outcome == "INSUFFICIENT_DATA":
        reasons.append(REASON_BUSINESS_SIC_INSUFFICIENT)
    if business_sic_outcome == "REVIEW_REQUIRED":
        reasons.append(REASON_BUSINESS_SIC_REVIEW)
    if business_sector_outcome == "INSUFFICIENT_DATA":
        reasons.append(REASON_BUSINESS_SECTOR_INSUFFICIENT)
    if business_sector_outcome == "REVIEW_REQUIRED":
        reasons.append(REASON_BUSINESS_SECTOR_REVIEW)
    for limitation in limitations:
        if limitation not in reasons:
            reasons.append(limitation)
    return tuple(reasons)


def _rule_outcome(screen: Optional[BusinessActivityScreenResult], suffix: str) -> Optional[str]:
    if screen is None:
        return None
    for rule in screen.rule_results:
        if suffix in str(rule.rule_id or "").lower():
            return str(rule.outcome)
    return None


def _period_from_financials(sec_financials: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not sec_financials:
        return None
    raw = sec_financials.get("financial_period_end")
    text = str(raw or "").strip()
    return text[:10] or None


def _accession_from_payload(payload: Mapping[str, Any], period: Optional[str]) -> Optional[str]:
    facts = (payload.get("facts") or {}).get("us-gaap") or {}
    for tag in (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ):
        units = ((facts.get(tag) or {}).get("units") or {})
        for items in units.values():
            for item in items or []:
                if not isinstance(item, Mapping):
                    continue
                if period and str(item.get("end") or "")[:10] != period:
                    continue
                if str(item.get("form") or "") not in {"10-K", "10-K/A", "20-F", "40-F"}:
                    continue
                accn = str(item.get("accn") or "").strip()
                if accn:
                    return accn
    return None


def _attribution_proves_zero(revenue_attribution: Any) -> bool:
    if revenue_attribution is None:
        return False
    if getattr(revenue_attribution, "status", None) != ATTRIBUTION_SUCCESS:
        return False
    if any(
        getattr(item, "mapping_status", None) == MAPPING_AMBIGUOUS
        for item in getattr(revenue_attribution, "items", ())
    ):
        return False
    prohibited = getattr(revenue_attribution, "prohibited_revenue", None)
    if prohibited is not None and float(prohibited) > 0:
        return False
    return can_conclude_zero_prohibited_revenue(revenue_attribution).allowed


def resolve_business_npr_from_cached_company_facts(
    symbol: str,
    raw_payload: Mapping[str, Any],
    *,
    sec_financials: Optional[Mapping[str, Any]] = None,
    source_identifier: str = "",
    cik: Optional[str] = None,
    methodology_id: Optional[str] = None,
    revenue_attribution: Any = None,
) -> CachedBusinessNprResolution:
    normalized = str(symbol or "").strip().upper()
    resolved_methodology = methodology_id or get_default_equity_methodology_id() or (
        "msci_islamic_index_series"
    )
    extracted = dict(sec_financials or {})
    if not extracted and raw_payload:
        extracted = SECFinancialClient(
            contact_email="cache-replay@localhost"
        ).extract_financials(dict(raw_payload))
    period = _period_from_financials(extracted)
    currency = str(extracted.get("financial_currency") or "") or None
    metadata = SECFinancialClient.extract_entity_metadata(dict(raw_payload))
    raw_segments = extract_revenue_segments_from_sec(
        raw_payload,
        sec_financials=extracted,
    )
    if period:
        raw_segments = tuple(
            segment
            for segment in raw_segments
            if not segment.fiscal_period or str(segment.fiscal_period)[:10] == period
        )
    business_segments = revenue_segments_to_business_evidence(raw_segments)
    business_evidence = enrich_business_activity_evidence(
        {"symbol": normalized, "cik": cik},
        sec_metadata=metadata,
        fmp_profile={},
        revenue_segments=business_segments,
        reported_total_revenue=extracted.get("revenue"),
    )
    npr_amount, npr_warnings = derive_non_permissible_revenue_amount(
        extracted.get("revenue"),
        business_evidence.revenue_segments,
        methodology_id=resolved_methodology,
        business_evidence=business_evidence,
        revenue_attribution=revenue_attribution,
    )
    proven_zero = npr_amount == 0.0 and _attribution_proves_zero(revenue_attribution)
    if npr_amount == 0.0 and not proven_zero:
        npr_amount = None
        if not npr_warnings:
            npr_warnings = (LIMITATION_NO_PROHIBITED_SEGMENT_EVIDENCE,)
    if npr_amount is None and not raw_segments and revenue_attribution is None:
        extra = LIMITATION_COMPANY_FACTS_NO_DIMENSIONAL_SEGMENTS
        if extra not in npr_warnings:
            npr_warnings = tuple((*npr_warnings, extra))

    business_screen = evaluate_business_activity(
        resolved_methodology,
        business_evidence,
        revenue_attribution=revenue_attribution,
    )
    resolution = build_participation_inputs_from_sec(
        normalized,
        extracted,
        cik=cik,
    )
    from dataclasses import replace

    inputs = replace(resolution.inputs, non_permissible_revenue=npr_amount)
    missing = blocking_missing_capabilities(
        resolved_methodology,
        financial_inputs=inputs,
        business_screen=business_screen,
        business_evidence_provided=True,
    )
    limitations = classify_npr_limitations(
        (*npr_warnings, *business_evidence.warnings, *business_screen.warnings)
    )
    npr_state = npr_state_from_amount(npr_amount, proven_zero=proven_zero)
    unresolved = classify_unresolved_npr_reasons(
        npr_amount=npr_amount,
        missing_capabilities=missing,
        financial_npr_outcome="INSUFFICIENT_DATA" if npr_amount is None else None,
        business_npr_outcome=_rule_outcome(business_screen, "non_permissible_revenue"),
        business_sic_outcome=_rule_outcome(business_screen, "sic_exclusions"),
        business_sector_outcome=_rule_outcome(business_screen, "sector_exclusions"),
        limitations=limitations,
    )
    digest = str(source_identifier or "").strip()
    accession = _accession_from_payload(raw_payload, period)
    provenance = (
        EvidenceProvenance(
            source_type=SOURCE_SEC_COMPANY_FACTS,
            source_identifier=digest or str(cik or metadata.get("entity_name") or normalized),
            period=period,
            filing_accession=accession,
            field="non_permissible_revenue",
            concept="us-gaap:Revenues",
            raw_or_derived=DERIVED_STATUS,
            resolution_reason=(
                limitations[0]
                if limitations
                else (
                    "proven_zero"
                    if npr_state == NPR_STATE_PROVEN_ZERO
                    else npr_state.lower()
                )
            ),
        ),
        EvidenceProvenance(
            source_type=SOURCE_SEC_COMPANY_FACTS,
            source_identifier=digest or str(cik or metadata.get("entity_name") or normalized),
            period=period,
            filing_accession=accession,
            field="sic_code",
            concept="sic",
            raw_or_derived=RAW_STATUS,
            resolution_reason=(
                "sic_present"
                if metadata.get("sic_code")
                else "company_facts_payload_has_no_sic"
            ),
        ),
    )
    return CachedBusinessNprResolution(
        symbol=normalized,
        npr_amount=npr_amount,
        npr_state=npr_state,
        unresolved_reasons=unresolved,
        limitations=limitations,
        company_facts_can_answer_npr=npr_state in {NPR_STATE_PROVEN_ZERO, NPR_STATE_POSITIVE},
        company_facts_can_answer_sic=bool(metadata.get("sic_code")),
        company_facts_can_answer_description=False,
        period=period,
        currency=currency,
        business_evidence=business_evidence,
        business_screen=business_screen,
        provenance=provenance,
        missing_capabilities=tuple(missing),
    )
