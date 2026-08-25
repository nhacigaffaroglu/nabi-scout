from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

PARTITION_COMPLETE = "COMPLETE"
PARTITION_PARTIAL = "PARTIAL"
PARTITION_OVERLAPPING = "OVERLAPPING"
PARTITION_AMBIGUOUS = "AMBIGUOUS"
PARTITION_UNUSABLE = "UNUSABLE"

ATTRIBUTION_SUCCESS = "SUCCESS"
ATTRIBUTION_FAIL_CLOSED = "FAIL_CLOSED"
ATTRIBUTION_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

MAPPING_DIRECT = "DIRECT"
MAPPING_DEFENSIBLE = "DEFENSIBLE_WITH_RULE"
MAPPING_NO_MATCH = "NO_MATCH"
MAPPING_AMBIGUOUS = "AMBIGUOUS"

PROHIBITED_MAPPING_STATUSES = frozenset({MAPPING_DIRECT, MAPPING_DEFENSIBLE})


@dataclass(frozen=True)
class RevenueAttributionItem:
    reported_label: str
    normalized_label: str
    concept: str
    axis: str
    member: str
    amount: float
    mapping_status: str
    msci_category: str
    mapping_rule_id: str
    rationale: str
    source: str
    context_id: str = ""
    unit: str = ""
    currency: str = "USD"
    period: str = ""
    accession: str = ""
    granularity: str = ""
    included_in_npr_calculation: bool = False
    included_in_safe_zero_partition: bool = False
    ambiguity_reason: str = ""
    semantic_type: str = ""
    semantic_reason: str = ""
    in_selected_partition: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RevenueAttributionView:
    symbol: str
    cik: str
    methodology: str
    methodology_version: str
    screening_period: str
    filing_accession: str
    filing_form: str
    filing_date: str
    filing_url: str
    primary_document: str
    denominator_name: str
    denominator_value: Optional[float]
    currency: str
    selected_axis: str
    partition_status: str
    partition_sum: Optional[float]
    partition_coverage: Optional[float]
    items: Tuple[RevenueAttributionItem, ...] = field(default_factory=tuple)
    supporting_items: Tuple[RevenueAttributionItem, ...] = field(default_factory=tuple)
    prohibited_revenue: Optional[float] = None
    prohibited_ratio: Optional[float] = None
    status: str = ATTRIBUTION_INSUFFICIENT_DATA
    confidence: str = "LOW"
    partition_granularity: str = ""
    attribution_quality: str = "INSUFFICIENT"
    limitations: Tuple[str, ...] = field(default_factory=tuple)
    provenance: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    log_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        payload["limitations"] = list(self.limitations)
        payload["provenance"] = list(self.provenance)
        return payload

    @property
    def is_usable_for_pass(self) -> bool:
        from services.participation_revenue_granularity import (
            ATTRIBUTION_QUALITY_HIGH,
            can_conclude_zero_prohibited_revenue,
        )

        if self.status != ATTRIBUTION_SUCCESS:
            return False
        if self.partition_status != PARTITION_COMPLETE:
            return False
        if self.denominator_value is None or self.denominator_value <= 0:
            return False
        if not self.items:
            return False
        if any(item.mapping_status == MAPPING_AMBIGUOUS for item in self.items):
            return False
        if (self.prohibited_revenue or 0) > 0:
            return True
        return (
            can_conclude_zero_prohibited_revenue(self).allowed
            and self.attribution_quality == ATTRIBUTION_QUALITY_HIGH
        )
