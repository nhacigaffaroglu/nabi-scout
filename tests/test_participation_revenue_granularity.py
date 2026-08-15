from __future__ import annotations

import unittest

from services.participation_business_engine import evaluate_business_activity
from services.participation_business_contract import BusinessRevenueEvidence
from services.participation_intelligence_contract import (
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.participation_revenue_attribution_contract import (
    ATTRIBUTION_FAIL_CLOSED,
    ATTRIBUTION_SUCCESS,
    MAPPING_NO_MATCH,
    PARTITION_COMPLETE,
    RevenueAttributionItem,
    RevenueAttributionView,
)
from services.participation_revenue_granularity import (
    ATTRIBUTION_QUALITY_HIGH,
    ATTRIBUTION_QUALITY_INSUFFICIENT,
    ATTRIBUTION_QUALITY_MEDIUM,
    GRANULARITY_BROAD_OPERATING_SEGMENT,
    GRANULARITY_BUSINESS_LINE_SPECIFIC,
    GRANULARITY_GEOGRAPHIC,
    GRANULARITY_PRODUCT_SERVICE_SPECIFIC,
    can_conclude_zero_prohibited_revenue,
    classify_member_granularity,
    finalize_attribution_view,
    has_material_other_bucket,
    partition_granularity_from_items,
)
from tests.test_participation_business_engine import evidence


def _item(label: str, amount: float, *, axis: str = "ProductOrServiceAxis") -> RevenueAttributionItem:
    return RevenueAttributionItem(
        reported_label=label,
        normalized_label=label.lower(),
        concept="us-gaap:Revenues",
        axis=axis,
        member=label.replace(" ", "") + "Member",
        amount=amount,
        mapping_status=MAPPING_NO_MATCH,
        msci_category="",
        mapping_rule_id="test",
        rationale="test",
        source="https://sec.gov",
    )


def _view(
    *,
    items: tuple[RevenueAttributionItem, ...],
    denominator: float = 100.0,
    axis: str = "ProductOrServiceAxis",
    granularity: str = "",
) -> RevenueAttributionView:
    return RevenueAttributionView(
        symbol="TEST",
        cik="1",
        methodology="msci_islamic_index_series",
        methodology_version="2025-05",
        screening_period="2025-12-31",
        filing_accession="0001",
        filing_form="10-K",
        filing_date="2026-01-01",
        filing_url="https://sec.gov",
        primary_document="t.htm",
        denominator_name="Revenues",
        denominator_value=denominator,
        currency="USD",
        selected_axis=axis,
        partition_status=PARTITION_COMPLETE,
        partition_sum=sum(item.amount for item in items),
        partition_coverage=sum(item.amount for item in items) / denominator,
        items=items,
        prohibited_revenue=0.0,
        prohibited_ratio=0.0,
        status=ATTRIBUTION_SUCCESS,
        partition_granularity=granularity or partition_granularity_from_items(items, selected_axis=axis),
    )


class GranularityClassificationTests(unittest.TestCase):
    def test_subscription_is_product_service_specific(self) -> None:
        result = classify_member_granularity("Subscription and Support")
        self.assertEqual(result.granularity, GRANULARITY_PRODUCT_SERVICE_SPECIFIC)

    def test_north_america_is_geographic(self) -> None:
        result = classify_member_granularity("North America", axis="StatementGeographicalAxis")
        self.assertEqual(result.granularity, GRANULARITY_GEOGRAPHIC)

    def test_google_services_is_broad(self) -> None:
        result = classify_member_granularity("Google Services")
        self.assertEqual(result.granularity, GRANULARITY_BROAD_OPERATING_SEGMENT)

    def test_innovative_medicine_is_business_line(self) -> None:
        result = classify_member_granularity("Innovative Medicine")
        self.assertEqual(result.granularity, GRANULARITY_BUSINESS_LINE_SPECIFIC)


class SafeZeroPolicyTests(unittest.TestCase):
    def test_geographic_complete_partition_cannot_zero(self) -> None:
        items = (
            _item("North America", 60.0, axis="StatementGeographicalAxis"),
            _item("International", 40.0, axis="StatementGeographicalAxis"),
        )
        view = _view(items=items, axis="StatementGeographicalAxis")
        safe = can_conclude_zero_prohibited_revenue(view)
        self.assertFalse(safe.allowed)
        self.assertEqual(safe.partition_granularity, GRANULARITY_GEOGRAPHIC)

    def test_broad_operating_segment_cannot_zero(self) -> None:
        items = (
            _item("Google Services", 80.0, axis="StatementBusinessSegmentsAxis"),
            _item("Google Cloud", 20.0, axis="StatementBusinessSegmentsAxis"),
        )
        view = _view(items=items, axis="StatementBusinessSegmentsAxis")
        safe = can_conclude_zero_prohibited_revenue(view)
        self.assertFalse(safe.allowed)

    def test_product_service_specific_may_zero(self) -> None:
        items = (
            _item("Subscription and Support", 95.0),
            _item("Professional Services and Other", 5.0),
        )
        view = _view(items=items)
        safe = can_conclude_zero_prohibited_revenue(view)
        self.assertTrue(safe.allowed)
        self.assertEqual(safe.attribution_quality, ATTRIBUTION_QUALITY_HIGH)

    def test_material_other_bucket_fail_closed(self) -> None:
        items = (_item("All Other", 10.0), _item("Subscription and Support", 90.0))
        self.assertTrue(has_material_other_bucket(items, denominator=100.0))
        view = _view(items=items)
        safe = can_conclude_zero_prohibited_revenue(view)
        self.assertFalse(safe.allowed)

    def test_finalize_downgrades_broad_partition(self) -> None:
        items = (
            _item("Family Of Apps", 90.0, axis="StatementBusinessSegmentsAxis"),
            _item("Reality Labs", 10.0, axis="StatementBusinessSegmentsAxis"),
        )
        draft = _view(items=items, axis="StatementBusinessSegmentsAxis")
        final = finalize_attribution_view(draft)
        self.assertEqual(final.status, ATTRIBUTION_FAIL_CLOSED)
        self.assertIsNone(final.prohibited_revenue)
        self.assertEqual(final.attribution_quality, ATTRIBUTION_QUALITY_MEDIUM)


class BusinessEngineGranularityTests(unittest.TestCase):
    def test_broad_segment_revenue_rule_insufficient(self) -> None:
        attr = finalize_attribution_view(
            _view(
                items=(
                    _item("Intelligent Cloud", 50.0, axis="StatementBusinessSegmentsAxis"),
                    _item("More Personal Computing", 50.0, axis="StatementBusinessSegmentsAxis"),
                ),
                axis="StatementBusinessSegmentsAxis",
            )
        )
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(
                reported_total_revenue=100.0,
                revenue_segments=(
                    BusinessRevenueEvidence(
                        category="no_match",
                        segment_name="Intelligent Cloud",
                        revenue_value=50.0,
                    ),
                    BusinessRevenueEvidence(
                        category="no_match",
                        segment_name="More Personal Computing",
                        revenue_value=50.0,
                    ),
                ),
            ),
            revenue_attribution=attr,
        )
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_INSUFFICIENT_DATA)

    def test_product_service_revenue_rule_pass(self) -> None:
        attr = finalize_attribution_view(
            _view(
                items=(
                    _item("Subscription and Support", 95.0),
                    _item("Professional Services and Other", 5.0),
                )
            )
        )
        result = evaluate_business_activity(
            "msci_islamic_index_series",
            evidence(
                reported_total_revenue=100.0,
                revenue_segments=(
                    BusinessRevenueEvidence(
                        category="no_match",
                        segment_name="Subscription and Support",
                        revenue_value=95.0,
                    ),
                    BusinessRevenueEvidence(
                        category="no_match",
                        segment_name="Professional Services and Other",
                        revenue_value=5.0,
                    ),
                ),
            ),
            revenue_attribution=attr,
        )
        revenue_rule = next(r for r in result.rule_results if "non_permissible_revenue" in r.rule_id)
        self.assertEqual(revenue_rule.outcome, RULE_OUTCOME_PASS)


if __name__ == "__main__":
    unittest.main()
