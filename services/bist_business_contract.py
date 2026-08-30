"""Structured BIST business-activity facts. No Participation verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.participation_business_contract import (
    EVIDENCE_COMPLETENESS_COMPLETE,
    EVIDENCE_COMPLETENESS_NONE,
    EVIDENCE_COMPLETENESS_PARTIAL,
)


BIST_BUSINESS_SOURCE_OFFICIAL = "official_issuer_reporting"
BIST_BUSINESS_SOURCE_FIXTURE = "NABI_TEST_BIST_BUSINESS"

# Existing Participation taxonomy keys only. No new religious categories.
CANONICAL_BUSINESS_CATEGORIES = frozenset(
    {
        "alcohol",
        "gambling",
        "tobacco",
        "conventional_banking",
        "pork",
        "adult_entertainment",
        "non_permissible",
        "weapons_defense",
        "technology",
        "general_services",
        "general_product",
        "unknown",
    }
)

CATEGORY_UNKNOWN = "unknown"

READINESS_NONE = EVIDENCE_COMPLETENESS_NONE
READINESS_PARTIAL = EVIDENCE_COMPLETENESS_PARTIAL
READINESS_COMPLETE = EVIDENCE_COMPLETENESS_COMPLETE


@dataclass(frozen=True)
class BistRawBusinessSegment:
    symbol: str
    segment_name: str
    currency: str
    period: str
    source: str
    issuer_id: Optional[str] = None
    segment_code: Optional[str] = None
    raw_category: str = ""
    revenue: Optional[float] = None
    period_end: Optional[str] = None
    source_document_id: Optional[str] = None
    as_of: Optional[str] = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "issuer_id": self.issuer_id,
            "segment_code": self.segment_code,
            "segment_name": self.segment_name,
            "raw_category": self.raw_category,
            "revenue": self.revenue,
            "currency": self.currency,
            "period": self.period,
            "period_end": self.period_end,
            "source": self.source,
            "source_document_id": self.source_document_id,
            "as_of": self.as_of,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class BistRawBusinessTotals:
    symbol: str
    currency: str
    period: str
    source: str
    total_revenue: Optional[float] = None
    period_end: Optional[str] = None
    source_document_id: Optional[str] = None
    as_of: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "total_revenue": self.total_revenue,
            "currency": self.currency,
            "period": self.period,
            "period_end": self.period_end,
            "source": self.source,
            "source_document_id": self.source_document_id,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class BistBusinessSegmentFact:
    symbol: str
    segment_name: str
    raw_category: str
    canonical_category: str
    mapping_rule: str
    currency: str
    period: str
    source: str
    issuer_id: Optional[str] = None
    segment_code: Optional[str] = None
    revenue: Optional[float] = None
    revenue_share: Optional[float] = None
    share_limitation: str = ""
    source_document_id: Optional[str] = None
    as_of: Optional[str] = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "issuer_id": self.issuer_id,
            "segment_code": self.segment_code,
            "segment_name": self.segment_name,
            "raw_category": self.raw_category,
            "canonical_category": self.canonical_category,
            "mapping_rule": self.mapping_rule,
            "revenue": self.revenue,
            "revenue_share": self.revenue_share,
            "share_limitation": self.share_limitation,
            "currency": self.currency,
            "period": self.period,
            "source": self.source,
            "source_document_id": self.source_document_id,
            "as_of": self.as_of,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class BistBusinessBundle:
    symbol: str
    identity_source: str
    segments: tuple[BistBusinessSegmentFact, ...]
    total_revenue: Optional[float]
    total_currency: str
    total_period: str
    unknown_revenue: Optional[float]
    unknown_share: Optional[float]
    mapped_share: Optional[float]
    readiness: str
    limitation: str = ""
    source: str = ""
    source_document_id: Optional[str] = None
    as_of: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "identity_source": self.identity_source,
            "segments": [item.to_dict() for item in self.segments],
            "total_revenue": self.total_revenue,
            "total_currency": self.total_currency,
            "total_period": self.total_period,
            "unknown_revenue": self.unknown_revenue,
            "unknown_share": self.unknown_share,
            "mapped_share": self.mapped_share,
            "readiness": self.readiness,
            "limitation": self.limitation,
            "source": self.source,
            "source_document_id": self.source_document_id,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class BistParticipationReadiness:
    symbol: str
    identity_source: str
    financial_input_readiness: str
    business_input_readiness: str
    final_participation_ready: bool
    limitation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "identity_source": self.identity_source,
            "financial_input_readiness": self.financial_input_readiness,
            "business_input_readiness": self.business_input_readiness,
            "final_participation_ready": self.final_participation_ready,
            "limitation": self.limitation,
        }
