"""Observability helpers for filing revenue evidence.

Does not change methodology, mapping, safe-zero, or NPR math.
Ambiguous items stay visible and remain excluded from conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional, Sequence, Tuple

from services.participation_revenue_attribution_contract import (
    MAPPING_AMBIGUOUS,
    MAPPING_NO_MATCH,
    PROHIBITED_MAPPING_STATUSES,
    RevenueAttributionItem,
    RevenueAttributionView,
)
from services.participation_revenue_granularity import (
    GRANULARITY_BROAD_OPERATING_SEGMENT,
    GRANULARITY_GEOGRAPHIC,
    GRANULARITY_UNKNOWN,
    can_conclude_zero_prohibited_revenue,
    classify_member_granularity,
    partition_granularity_from_items,
)

REASON_NO_METHODOLOGY_MAPPING = "NO_METHODOLOGY_MAPPING"
REASON_LABEL_TOO_BROAD = "LABEL_TOO_BROAD"
REASON_MIXED_ACTIVITY_CATEGORY = "MIXED_ACTIVITY_CATEGORY"
REASON_OTHER_OR_UNALLOCATED = "OTHER_OR_UNALLOCATED"
REASON_INSUFFICIENT_ACTIVITY_SPECIFICITY = "INSUFFICIENT_ACTIVITY_SPECIFICITY"

_MIXED_ACTIVITY_RULE_IDS = frozenset(
    {
        "msci.rev.ambiguous.financial",
        "msci.rev.ambiguous.entertainment",
    }
)
_OTHER_LABEL_MARKERS = (
    "other",
    "all other",
    "unallocated",
    "miscellaneous",
    "corporate",
    "eliminations",
)


@dataclass(frozen=True)
class RevenueEvidenceCoverage:
    total_filing_revenue: Optional[float]
    mapped_permissible_revenue: float
    mapped_prohibited_revenue: float
    ambiguous_revenue: float
    unattributed_revenue: Optional[float]
    coverage: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_filing_revenue": self.total_filing_revenue,
            "mapped_permissible_revenue": self.mapped_permissible_revenue,
            "mapped_prohibited_revenue": self.mapped_prohibited_revenue,
            "ambiguous_revenue": self.ambiguous_revenue,
            "unattributed_revenue": self.unattributed_revenue,
            "coverage": self.coverage,
        }


def classify_ambiguity_reason(
    item: RevenueAttributionItem,
    *,
    granularity: str = "",
) -> str:
    if item.mapping_status != MAPPING_AMBIGUOUS:
        return ""
    rule_id = str(item.mapping_rule_id or "")
    label = str(item.normalized_label or item.reported_label or "").strip().lower()
    if rule_id in _MIXED_ACTIVITY_RULE_IDS:
        return REASON_MIXED_ACTIVITY_CATEGORY
    if any(marker == label or f" {marker} " in f" {label} " for marker in _OTHER_LABEL_MARKERS):
        return REASON_OTHER_OR_UNALLOCATED
    if rule_id in {"msci.rev.unmapped", "msci.rev.unlabeled"} or not label:
        return REASON_NO_METHODOLOGY_MAPPING
    level = granularity or item.granularity
    if level in {
        GRANULARITY_BROAD_OPERATING_SEGMENT,
        GRANULARITY_GEOGRAPHIC,
        GRANULARITY_UNKNOWN,
    }:
        return REASON_LABEL_TOO_BROAD
    return REASON_INSUFFICIENT_ACTIVITY_SPECIFICITY


def build_revenue_evidence_coverage(
    view: Optional[RevenueAttributionView],
    *,
    canonical_revenue: Optional[float] = None,
) -> RevenueEvidenceCoverage:
    if view is None:
        return RevenueEvidenceCoverage(
            total_filing_revenue=canonical_revenue,
            mapped_permissible_revenue=0.0,
            mapped_prohibited_revenue=0.0,
            ambiguous_revenue=0.0,
            unattributed_revenue=canonical_revenue,
            coverage=None,
        )
    total = view.denominator_value
    if total is None and canonical_revenue is not None:
        total = canonical_revenue
    permissible = sum(
        item.amount
        for item in view.items
        if item.mapping_status == MAPPING_NO_MATCH
    )
    prohibited = sum(
        item.amount
        for item in view.items
        if item.mapping_status in PROHIBITED_MAPPING_STATUSES
    )
    ambiguous = sum(
        item.amount
        for item in view.items
        if item.mapping_status == MAPPING_AMBIGUOUS
    )
    attributed = permissible + prohibited + ambiguous
    unattributed = None
    if total is not None:
        unattributed = max(0.0, float(total) - attributed)
    coverage = view.partition_coverage
    if coverage is None and total and attributed:
        coverage = attributed / float(total)
    return RevenueEvidenceCoverage(
        total_filing_revenue=total,
        mapped_permissible_revenue=permissible,
        mapped_prohibited_revenue=prohibited,
        ambiguous_revenue=ambiguous,
        unattributed_revenue=unattributed,
        coverage=coverage,
    )


def annotate_revenue_evidence(view: RevenueAttributionView) -> RevenueAttributionView:
    """Attach audit flags. Does not change mapping or conclusion fields."""
    safe_zero_allowed = can_conclude_zero_prohibited_revenue(view).allowed
    annotated: list[RevenueAttributionItem] = []
    for item in view.items:
        granularity = item.granularity or classify_member_granularity(
            item.reported_label,
            axis=item.axis or view.selected_axis,
        ).granularity
        prohibited = item.mapping_status in PROHIBITED_MAPPING_STATUSES
        ambiguous = item.mapping_status == MAPPING_AMBIGUOUS
        annotated.append(
            replace(
                item,
                granularity=granularity,
                included_in_npr_calculation=prohibited,
                included_in_safe_zero_partition=bool(
                    safe_zero_allowed and not prohibited and not ambiguous
                ),
                ambiguity_reason=(
                    classify_ambiguity_reason(item, granularity=granularity)
                    if ambiguous
                    else ""
                ),
                period=item.period or view.screening_period,
                accession=item.accession or view.filing_accession,
            )
        )
    partition_granularity = view.partition_granularity or partition_granularity_from_items(
        annotated,
        selected_axis=view.selected_axis,
    )
    return replace(
        view,
        items=tuple(annotated),
        partition_granularity=partition_granularity,
    )


def retained_item_records(
    items: Sequence[RevenueAttributionItem],
) -> Tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "label": item.reported_label,
                "concept": item.concept,
                "dimension": item.axis,
                "member": item.member,
                "value": item.amount,
                "unit": item.unit or item.currency,
                "period": item.period,
                "accession": item.accession,
                "source": item.source,
                "mapping": item.mapping_status,
                "mapping_reason": item.rationale,
                "mapping_rule_id": item.mapping_rule_id,
                "granularity": item.granularity,
                "included_in_npr_calculation": item.included_in_npr_calculation,
                "included_in_safe_zero_partition": item.included_in_safe_zero_partition,
                "ambiguity_reason": item.ambiguity_reason,
            }
        )
    return tuple(rows)
