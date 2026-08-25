"""Replayable NPR resolution from cached SEC primary filings.

Reuses the canonical inline XBRL parser, MSCI mapper, and safe-zero contract.
Does not change methodology. Missing evidence stays None.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.participation_business_evidence_enrichment import (
    derive_non_permissible_revenue_amount,
)
from services.participation_inline_xbrl_attribution import (
    build_revenue_attribution_from_document,
)
from services.participation_intelligence_contract import (
    ASSET_KIND_EQUITY,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
)
from services.participation_intelligence_service import (
    build_combined_methodology_assessment,
)
from services.participation_methodology_registry import get_default_equity_methodology_id
from services.participation_pass_logic import can_emit_uygun
from services.participation_revenue_attribution_contract import (
    MAPPING_AMBIGUOUS,
    PARTITION_COMPLETE,
    RevenueAttributionView,
)
from services.participation_revenue_granularity import (
    LIMITATION_BROAD_PARTITION,
    LIMITATION_MATERIAL_OTHER,
    can_conclude_zero_prohibited_revenue,
    partition_granularity_from_items,
)
from services.participation_revenue_evidence_presentation import (
    RevenueEvidenceCoverage,
    build_revenue_evidence_coverage,
    retained_item_records,
)
from services.sec_filing_evidence import SecFilingEvidence
from services.sec_inline_xbrl_parser import parse_inline_xbrl_document

CLASS_NPR_PROVEN_AMOUNT = "NPR_PROVEN_AMOUNT"
CLASS_NPR_PROVEN_ZERO = "NPR_PROVEN_ZERO"
CLASS_ATTRIBUTION_PRESENT_BUT_TOO_BROAD = "ATTRIBUTION_PRESENT_BUT_TOO_BROAD"
CLASS_ATTRIBUTION_INCOMPLETE = "ATTRIBUTION_INCOMPLETE"
CLASS_MAPPING_AMBIGUOUS = "MAPPING_AMBIGUOUS"
CLASS_FILING_HAS_NO_USABLE_ATTRIBUTION = "FILING_HAS_NO_USABLE_ATTRIBUTION"
CLASS_PERIOD_MISMATCH = "PERIOD_MISMATCH"
CLASS_PARSER_LIMITATION = "PARSER_LIMITATION"

_COVERAGE_TOLERANCE = 0.02  # existing partition tolerance; do not invent another


@dataclass(frozen=True)
class FilingNprResolution:
    symbol: str
    cik: str
    accession: str
    form: str
    filing_date: str
    canonical_period: Optional[str]
    screening_period: Optional[str]
    period_match: bool
    parser_success: bool
    candidate_count: int
    granularity: str
    canonical_revenue: Optional[float]
    attributed_revenue: Optional[float]
    coverage: Optional[float]
    mapping_ambiguous: bool
    npr_amount: Optional[float]
    npr_state: str
    safe_zero: bool
    classification: str
    limitations: Tuple[str, ...]
    provenance: Tuple[Tuple[str, str], ...]
    attribution: Optional[RevenueAttributionView] = None
    evidence_coverage: Optional[RevenueEvidenceCoverage] = None
    retained_items: Tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "cik": self.cik,
            "accession": self.accession,
            "form": self.form,
            "filing_date": self.filing_date,
            "canonical_period": self.canonical_period,
            "screening_period": self.screening_period,
            "period_match": self.period_match,
            "parser_success": self.parser_success,
            "candidate_count": self.candidate_count,
            "granularity": self.granularity,
            "canonical_revenue": self.canonical_revenue,
            "attributed_revenue": self.attributed_revenue,
            "coverage": self.coverage,
            "mapping_ambiguous": self.mapping_ambiguous,
            "npr_amount": self.npr_amount,
            "npr_state": self.npr_state,
            "safe_zero": self.safe_zero,
            "classification": self.classification,
            "limitations": list(self.limitations),
            "provenance": list(self.provenance),
            "evidence_coverage": (
                self.evidence_coverage.to_dict() if self.evidence_coverage else None
            ),
            "retained_items": list(self.retained_items),
        }


def _period_matches(left: Optional[str], right: Optional[str]) -> bool:
    if not left or not right:
        return False
    return str(left)[:10] == str(right)[:10]


def classify_filing_npr_outcome(
    *,
    parser_success: bool,
    period_match: bool,
    attribution: Optional[RevenueAttributionView],
    npr_amount: Optional[float],
    safe_zero: bool,
) -> str:
    if not parser_success:
        return CLASS_PARSER_LIMITATION
    if not period_match:
        return CLASS_PERIOD_MISMATCH
    if attribution is None:
        return CLASS_FILING_HAS_NO_USABLE_ATTRIBUTION
    limitations = " | ".join(attribution.limitations or ())
    if any(
        getattr(item, "mapping_status", None) == MAPPING_AMBIGUOUS
        for item in attribution.items
    ) or "ambiguous under MSCI taxonomy" in limitations:
        return CLASS_MAPPING_AMBIGUOUS
    if LIMITATION_BROAD_PARTITION in limitations:
        return CLASS_ATTRIBUTION_PRESENT_BUT_TOO_BROAD
    if npr_amount is not None and float(npr_amount) > 0:
        return CLASS_NPR_PROVEN_AMOUNT
    if safe_zero and npr_amount == 0.0:
        return CLASS_NPR_PROVEN_ZERO
    if attribution.items and attribution.partition_status != PARTITION_COMPLETE:
        return CLASS_ATTRIBUTION_INCOMPLETE
    if attribution.items and LIMITATION_MATERIAL_OTHER in limitations:
        return CLASS_ATTRIBUTION_INCOMPLETE
    if not attribution.items:
        return CLASS_FILING_HAS_NO_USABLE_ATTRIBUTION
    return CLASS_ATTRIBUTION_INCOMPLETE


def resolve_npr_from_cached_filing(
    evidence: SecFilingEvidence,
    *,
    canonical_period: Optional[str] = None,
    canonical_revenue: Optional[float] = None,
    methodology_id: Optional[str] = None,
    methodology_version: str = "2025-05",
    prohibited_categories: Sequence[str] = (),
) -> FilingNprResolution:
    resolved_methodology = methodology_id or get_default_equity_methodology_id() or (
        "msci_islamic_index_series"
    )
    filing_ref = evidence.filing_ref()
    parser_success = False
    attribution: Optional[RevenueAttributionView] = None
    limitations: list[str] = []
    try:
        document = parse_inline_xbrl_document(evidence.raw_bytes)
        parser_success = True
        attribution = build_revenue_attribution_from_document(
            document,
            symbol=evidence.symbol,
            filing_ref=filing_ref,
            methodology_id=resolved_methodology,
            methodology_version=methodology_version,
            prohibited_categories=prohibited_categories,
            preferred_period_end=canonical_period,
        )
    except Exception:
        limitations.append("Inline XBRL parse failed.")
        attribution = None

    screening_period = attribution.screening_period if attribution else None
    period_match = _period_matches(canonical_period, screening_period)
    if canonical_period and screening_period and not period_match:
        limitations.append("Canonical financial period and filing attribution period differ.")

    npr_amount = None
    npr_warnings: Tuple[str, ...] = ()
    safe_zero = False
    if attribution is not None and period_match:
        npr_amount, npr_warnings = derive_non_permissible_revenue_amount(
            canonical_revenue if canonical_revenue is not None else attribution.denominator_value,
            (),
            methodology_id=resolved_methodology,
            revenue_attribution=attribution,
        )
        if npr_amount == 0.0:
            safe_zero = can_conclude_zero_prohibited_revenue(attribution).allowed
            if not safe_zero:
                npr_amount = None
        if npr_amount is not None and float(npr_amount) > 0:
            safe_zero = False
        limitations.extend(npr_warnings)
        limitations.extend(attribution.limitations)

    granularity = ""
    attributed = None
    coverage = None
    mapping_ambiguous = False
    candidate_count = 0
    if attribution is not None:
        candidate_count = len(attribution.items)
        granularity = attribution.partition_granularity or partition_granularity_from_items(
            attribution.items,
            selected_axis=attribution.selected_axis,
        )
        attributed = attribution.partition_sum
        coverage = attribution.partition_coverage
        mapping_ambiguous = any(
            item.mapping_status == MAPPING_AMBIGUOUS for item in attribution.items
        ) or any(
            "ambiguous under MSCI taxonomy" in str(item)
            for item in attribution.limitations
        )
        if coverage is None and attributed and attribution.denominator_value:
            coverage = attributed / attribution.denominator_value

    unique_limitations = tuple(dict.fromkeys(item for item in limitations if item))
    classification = classify_filing_npr_outcome(
        parser_success=parser_success,
        period_match=period_match if canonical_period else parser_success,
        attribution=attribution,
        npr_amount=npr_amount,
        safe_zero=safe_zero,
    )
    if not canonical_period:
        period_match = parser_success and bool(screening_period)

    npr_state = (
        "POSITIVE"
        if npr_amount is not None and float(npr_amount) > 0
        else "PROVEN_ZERO"
        if safe_zero and npr_amount == 0.0
        else "MISSING"
    )
    provenance = (
        ("source_type", evidence.source),
        ("source_identifier", evidence.content_digest),
        ("accession", evidence.accession),
        ("form", evidence.form),
        ("filing_date", evidence.filing_date),
        ("period", str(screening_period or "")),
        ("canonical_period", str(canonical_period or "")),
        ("field", "non_permissible_revenue"),
        ("raw_or_derived", "derived"),
        ("resolution_reason", classification),
    )
    return FilingNprResolution(
        symbol=evidence.symbol,
        cik=evidence.cik,
        accession=evidence.accession,
        form=evidence.form,
        filing_date=evidence.filing_date,
        canonical_period=canonical_period,
        screening_period=screening_period,
        period_match=period_match,
        parser_success=parser_success,
        candidate_count=candidate_count,
        granularity=granularity,
        canonical_revenue=canonical_revenue,
        attributed_revenue=attributed,
        coverage=coverage,
        mapping_ambiguous=mapping_ambiguous,
        npr_amount=npr_amount,
        npr_state=npr_state,
        safe_zero=safe_zero,
        classification=classification,
        limitations=unique_limitations,
        provenance=provenance,
        attribution=attribution,
        evidence_coverage=build_revenue_evidence_coverage(
            attribution,
            canonical_revenue=canonical_revenue,
        ),
        retained_items=retained_item_records(attribution.items) if attribution else (),
    )


def assess_with_filing_npr(
    *,
    symbol: str,
    financial_inputs,
    business_evidence,
    filing_resolution: FilingNprResolution,
    methodology_id: Optional[str] = None,
):
    """Dry-run combined assessment using filing NPR. No persistence."""
    from services.participation_business_engine import evaluate_business_activity
    from services.participation_financial_engine import evaluate_financial_rules
    from services.participation_methodology_capabilities import blocking_missing_capabilities

    mid = methodology_id or get_default_equity_methodology_id() or "msci_islamic_index_series"
    inputs = replace(financial_inputs, non_permissible_revenue=filing_resolution.npr_amount)
    financial = evaluate_financial_rules(mid, inputs)
    business = evaluate_business_activity(
        mid,
        business_evidence,
        revenue_attribution=filing_resolution.attribution,
    )
    assessment = build_combined_methodology_assessment(
        financial,
        business,
        asset_kind=ASSET_KIND_EQUITY,
    )
    missing = blocking_missing_capabilities(
        mid,
        financial_inputs=inputs,
        business_screen=business,
        business_evidence_provided=True,
    )
    status = assessment.status or PARTICIPATION_STATUS_KONTROL_ET
    if status == PARTICIPATION_STATUS_UYGUN and not can_emit_uygun(
        methodology_id=mid,
        financial_screen=financial,
        business_screen=business,
        missing_capabilities=missing,
    ):
        status = PARTICIPATION_STATUS_KONTROL_ET
    return {
        "symbol": symbol,
        "status": status,
        "financial": financial.overall_outcome,
        "business": business.overall_outcome,
        "npr": filing_resolution.npr_amount,
        "missing": list(missing),
        "classification": filing_resolution.classification,
    }
