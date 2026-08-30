"""Public KAP / official-issuer business-segment evidence vocabulary.

Acquisition and extraction only. Does not evaluate Participation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


SOURCE_PUBLIC_KAP_BUSINESS = "PUBLIC_KAP_OFFICIAL_NOTES"
SOURCE_TYPE_FINANCIAL_REPORT = "KAP_FINANCIAL_REPORT"
SOURCE_TYPE_ACTIVITY_REPORT = "KAP_ACTIVITY_REPORT"
SOURCE_TYPE_OFFICIAL_PDF_NOTES = "KAP_OFFICIAL_PDF_NOTES"

BREAKDOWN_OPERATING_SEGMENT = "operating_segment"
BREAKDOWN_GEOGRAPHICAL = "geographical_revenue"
BREAKDOWN_SINGLE_SEGMENT = "single_operating_segment"

STRUCTURED_SEGMENT_YES = "YES"
STRUCTURED_SEGMENT_NO = "NO"

GAP_AVAILABLE_FROM_PUBLIC_KAP = "AVAILABLE_FROM_PUBLIC_KAP"
GAP_DERIVABLE_SAFELY = "DERIVABLE_SAFELY"
GAP_REQUIRES_OTHER_PUBLIC_SOURCE = "REQUIRES_OTHER_PUBLIC_SOURCE"
GAP_METHODOLOGY_UNRESOLVED = "METHODOLOGY_UNRESOLVED"

COVERAGE_PERIOD_INCOMPATIBLE = "PERIOD_INCOMPATIBLE"
COVERAGE_CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
COVERAGE_MISSING_FINANCIAL_TOTAL = "MISSING_1E_TOTAL"
COVERAGE_OK = "COMPARABLE"

SHADOW_RESULT_KIND = "BUSINESS_SCREEN_SHADOW_RESULT"

# Public disclosure pages inspected for the 1F pilot. Not a classification.
PILOT_PUBLIC_BUSINESS_SOURCES = {
    "ASELS": {
        "financial_report_id": "1643141",
        "activity_report_id": "1643140",
        "official_pdf_file_id": "4028328c9f52dc40019fcd5c3b0b7297",
        "official_pdf_name": "ASELSAN SPK RAPORU 30.06.2026.pdf",
        "period": "YTD",
        "period_end": "2026-06-30",
        "source_type": SOURCE_TYPE_OFFICIAL_PDF_NOTES,
    },
    "BIMAS": {
        "financial_report_id": "1651656",
        "activity_report_id": "1651657",
        "official_pdf_file_id": "4028328c9f52dc4001a010eec8f10efb",
        "official_pdf_name": "BIM - 30.06.2026 TR.pdf",
        "period": "YTD",
        "period_end": "2026-06-30",
        "source_type": SOURCE_TYPE_OFFICIAL_PDF_NOTES,
    },
    "TUPRS": {
        "financial_report_id": "1643116",
        "activity_report_id": "1643117",
        "official_pdf_file_id": "4028328d9f52dddd019fccda450b236b",
        "official_pdf_name": "tupras-konsolide-spk-30062026.pdf",
        "period": "YTD",
        "period_end": "2026-06-30",
        "source_type": SOURCE_TYPE_OFFICIAL_PDF_NOTES,
    },
}

# Tokens used only to *search* public taxonomy. Not a mapping table.
SEGMENT_TAXONOMY_SEARCH_TOKENS = (
    "OperatingSegment",
    "SegmentRevenue",
    "RevenueFromExternalCustomers",
    "GeographicalAreas",
    "MajorCustomer",
    "DisclosureOfOperatingSegments",
)

# Observed on public FR pages. Standard P&L template line, not IFRS 8 segments.
NON_SEGMENT_TEMPLATE_CONCEPTS = frozenset(
    {
        "kap-fr_RevenueFromFinanceSectorOperations",
        "kap-fr_CostOfFinanceSectorOperations",
        "kap-fr_GrossProfitLossFromFinanceSectorOperations",
        "kap-fr_OtherRevenuesFromFinanceSectorOperations",
        "kap-fr_OtherExpensesRelatedWithFinanceSectorOperations",
    }
)

PARTICIPATION_FINANCIAL_GAP_FIELDS = (
    "cash_and_interest_bearing_securities",
    "accounts_receivable",
    "non_permissible_revenue",
    "interest_bearing_debt",
    "market_capitalization",
    "average_market_cap_24m",
)


@dataclass(frozen=True)
class KapPublicSegmentEvidence:
    """Official extracted row. Not a Participation category."""

    symbol: str
    segment_name: str
    currency: str
    period: str
    source: str
    breakdown_kind: str
    raw_revenue: Optional[float] = None
    unit_scale: Optional[int] = None
    unit_label: str = ""
    period_end: Optional[str] = None
    period_start: Optional[str] = None
    location: str = ""
    source_document_id: Optional[str] = None
    source_url: str = ""
    activity_description: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "segment_name": self.segment_name,
            "raw_revenue": self.raw_revenue,
            "unit_scale": self.unit_scale,
            "unit_label": self.unit_label,
            "currency": self.currency,
            "period": self.period,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "source": self.source,
            "source_document_id": self.source_document_id,
            "source_url": self.source_url,
            "breakdown_kind": self.breakdown_kind,
            "location": self.location,
            "activity_description": self.activity_description,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class KapPublicBusinessDocument:
    symbol: str
    disclosure_id: str
    source_url: str
    source_type: str
    period: str
    period_end: Optional[str]
    currency: str
    unit_label: str
    unit_scale: Optional[int]
    structured_segment_taxonomy: str
    observed_taxonomy: tuple[str, ...]
    narrative_fallback_used: bool
    official_total_revenue: Optional[float]
    segments: tuple[KapPublicSegmentEvidence, ...]
    limitation: str = ""
    cached: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "disclosure_id": self.disclosure_id,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "period": self.period,
            "period_end": self.period_end,
            "currency": self.currency,
            "unit_label": self.unit_label,
            "unit_scale": self.unit_scale,
            "structured_segment_taxonomy": self.structured_segment_taxonomy,
            "observed_taxonomy": list(self.observed_taxonomy),
            "narrative_fallback_used": self.narrative_fallback_used,
            "official_total_revenue": self.official_total_revenue,
            "segments": [item.to_dict() for item in self.segments],
            "limitation": self.limitation,
            "cached": self.cached,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class KapPublicRevenueCoverage:
    symbol: str
    coverage_ratio: Optional[float]
    unexplained_remainder: Optional[float]
    segment_revenue_total: Optional[float]
    financial_total_revenue: Optional[float]
    status: str
    period_match: bool
    currency_match: bool
    used_1e_denominator_for_shares: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "coverage_ratio": self.coverage_ratio,
            "unexplained_remainder": self.unexplained_remainder,
            "segment_revenue_total": self.segment_revenue_total,
            "financial_total_revenue": self.financial_total_revenue,
            "status": self.status,
            "period_match": self.period_match,
            "currency_match": self.currency_match,
            "used_1e_denominator_for_shares": self.used_1e_denominator_for_shares,
        }


@dataclass(frozen=True)
class KapFinancialGap:
    field: str
    status: str
    observed_concepts: tuple[str, ...]
    likely_public_source: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "status": self.status,
            "observed_concepts": list(self.observed_concepts),
            "likely_public_source": self.likely_public_source,
            "note": self.note,
        }


@dataclass(frozen=True)
class KapBusinessScreenShadow:
    """Read-only business-screen output. Not a Participation status."""

    result_kind: str
    symbol: str
    overall_outcome: str
    evidence_completeness: str
    methodology_complete: bool
    persisted: bool = False
    not_participation_status: bool = True
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_kind": self.result_kind,
            "symbol": self.symbol,
            "overall_outcome": self.overall_outcome,
            "evidence_completeness": self.evidence_completeness,
            "methodology_complete": self.methodology_complete,
            "persisted": self.persisted,
            "not_participation_status": self.not_participation_status,
            "warnings": list(self.warnings),
        }
