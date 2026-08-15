from __future__ import annotations

from typing import Optional, Sequence, Tuple

from services.participation_business_contract import BusinessRevenueEvidence
from services.participation_msci_revenue_mapper import is_prohibited_mapping, map_revenue_member_to_msci
from services.participation_revenue_attribution_contract import RevenueAttributionView
from services.participation_intelligence_contract import CONFIDENCE_HIGH, CONFIDENCE_LOW


def attribution_items_to_business_evidence(
    view: RevenueAttributionView,
) -> Tuple[BusinessRevenueEvidence, ...]:
    if not view.items:
        return ()

    denominator = view.denominator_value or 0.0
    segments: list[BusinessRevenueEvidence] = []
    for item in view.items:
        mapping = map_revenue_member_to_msci(item.reported_label)
        category = "non_permissible" if is_prohibited_mapping(mapping) else mapping.mapping_status.lower()
        revenue_pct = None
        if denominator > 0:
            revenue_pct = item.amount / denominator * 100.0
        segments.append(
            BusinessRevenueEvidence(
                category=category,
                segment_name=item.reported_label,
                revenue_value=item.amount,
                revenue_pct=revenue_pct,
                source="SEC 10-K Inline XBRL",
                source_date=None,
                confidence=CONFIDENCE_HIGH if view.confidence == "HIGH" else CONFIDENCE_LOW,
            )
        )
    return tuple(segments)


def should_attempt_inline_xbrl_attribution(
    *,
    existing_segment_count: int,
    total_revenue: Optional[float],
) -> bool:
    if existing_segment_count > 0:
        return False
    return total_revenue is not None and total_revenue > 0
