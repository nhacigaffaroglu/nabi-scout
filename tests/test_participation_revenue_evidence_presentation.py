from __future__ import annotations

import unittest

from services.participation_revenue_attribution_contract import (
    MAPPING_AMBIGUOUS,
    MAPPING_DIRECT,
    MAPPING_NO_MATCH,
    PARTITION_COMPLETE,
    RevenueAttributionItem,
    RevenueAttributionView,
)
from services.participation_revenue_evidence_presentation import (
    REASON_MIXED_ACTIVITY_CATEGORY,
    REASON_NO_METHODOLOGY_MAPPING,
    annotate_revenue_evidence,
    build_revenue_evidence_coverage,
    classify_ambiguity_reason,
)
from services.participation_revenue_granularity import (
    can_conclude_zero_prohibited_revenue,
    finalize_attribution_view,
)
from tests.test_participation_filing_npr_resolver import (
    AMBIGUOUS_IXBRL,
    CRM_MINIMAL_IXBRL,
    PROHIBITED_IXBRL,
    _evidence,
)
from services.participation_filing_npr_resolver import resolve_npr_from_cached_filing


def _item(
    label: str,
    amount: float,
    *,
    mapping: str = MAPPING_NO_MATCH,
    rule_id: str = "msci.rev.nomatch.subscription",
    rationale: str = "test",
) -> RevenueAttributionItem:
    return RevenueAttributionItem(
        reported_label=label,
        normalized_label=label.lower(),
        concept="us-gaap:Revenues",
        axis="ProductOrServiceAxis",
        member=label.replace(" ", "") + "Member",
        amount=amount,
        mapping_status=mapping,
        msci_category="gambling" if mapping == MAPPING_DIRECT else "",
        mapping_rule_id=rule_id,
        rationale=rationale,
        source="https://sec.gov",
    )


def _view(items: tuple[RevenueAttributionItem, ...]) -> RevenueAttributionView:
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
        denominator_value=100.0,
        currency="USD",
        selected_axis="ProductOrServiceAxis",
        partition_status=PARTITION_COMPLETE,
        partition_sum=sum(item.amount for item in items),
        partition_coverage=sum(item.amount for item in items) / 100.0,
        items=items,
        prohibited_revenue=0.0,
        status="SUCCESS",
    )


class AmbiguityTaxonomyTests(unittest.TestCase):
    def test_unmapped_is_no_methodology_mapping(self) -> None:
        item = _item("Forestry", 10.0, mapping=MAPPING_AMBIGUOUS, rule_id="msci.rev.unmapped")
        self.assertEqual(classify_ambiguity_reason(item), REASON_NO_METHODOLOGY_MAPPING)

    def test_financial_is_mixed_activity(self) -> None:
        item = _item(
            "Financial Services",
            10.0,
            mapping=MAPPING_AMBIGUOUS,
            rule_id="msci.rev.ambiguous.financial",
        )
        self.assertEqual(classify_ambiguity_reason(item), REASON_MIXED_ACTIVITY_CATEGORY)

    def test_non_ambiguous_has_no_reason(self) -> None:
        self.assertEqual(classify_ambiguity_reason(_item("Subscription", 10.0)), "")


class EvidenceSeparationTests(unittest.TestCase):
    def test_ambiguous_is_not_permissible_or_zero(self) -> None:
        view = annotate_revenue_evidence(
            _view(
                (
                    _item("Subscription", 80.0),
                    _item(
                        "Financial Services",
                        20.0,
                        mapping=MAPPING_AMBIGUOUS,
                        rule_id="msci.rev.ambiguous.financial",
                    ),
                )
            )
        )
        coverage = build_revenue_evidence_coverage(view)
        self.assertEqual(coverage.mapped_permissible_revenue, 80.0)
        self.assertEqual(coverage.ambiguous_revenue, 20.0)
        self.assertEqual(coverage.mapped_prohibited_revenue, 0.0)
        ambiguous = [item for item in view.items if item.mapping_status == MAPPING_AMBIGUOUS]
        self.assertEqual(len(ambiguous), 1)
        self.assertFalse(ambiguous[0].included_in_npr_calculation)
        self.assertFalse(ambiguous[0].included_in_safe_zero_partition)
        self.assertFalse(can_conclude_zero_prohibited_revenue(view).allowed)

    def test_ambiguous_excluded_from_safe_zero_after_finalize(self) -> None:
        view = finalize_attribution_view(
            _view(
                (
                    _item("Subscription and support", 80.0),
                    _item(
                        "Financial Services",
                        20.0,
                        mapping=MAPPING_AMBIGUOUS,
                        rule_id="msci.rev.ambiguous.financial",
                    ),
                )
            )
        )
        annotated = annotate_revenue_evidence(view)
        self.assertFalse(can_conclude_zero_prohibited_revenue(annotated).allowed)
        self.assertFalse(
            any(item.included_in_safe_zero_partition for item in annotated.items)
        )

    def test_prohibited_still_counts(self) -> None:
        result = resolve_npr_from_cached_filing(
            _evidence(PROHIBITED_IXBRL, symbol="TEST"),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertEqual(result.npr_amount, 2_137_000_000.0)
        prohibited = [
            item
            for item in result.retained_items
            if item["mapping"] == MAPPING_DIRECT
        ]
        self.assertTrue(prohibited)
        self.assertTrue(all(item["included_in_npr_calculation"] for item in prohibited))
        self.assertFalse(any(item["included_in_safe_zero_partition"] for item in prohibited))

    def test_permissible_safe_zero_unchanged(self) -> None:
        result = resolve_npr_from_cached_filing(
            _evidence(CRM_MINIMAL_IXBRL),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertEqual(result.npr_amount, 0.0)
        self.assertTrue(result.safe_zero)
        self.assertTrue(result.retained_items)
        self.assertTrue(
            all(item["included_in_safe_zero_partition"] for item in result.retained_items)
        )
        self.assertFalse(
            any(item["included_in_npr_calculation"] for item in result.retained_items)
        )
        self.assertEqual(result.evidence_coverage.ambiguous_revenue, 0.0)

    def test_ambiguous_items_are_retained_and_auditable(self) -> None:
        result = resolve_npr_from_cached_filing(
            _evidence(AMBIGUOUS_IXBRL, symbol="ACN"),
            canonical_period="2026-01-31",
            canonical_revenue=41_525_000_000.0,
        )
        self.assertIsNone(result.npr_amount)
        self.assertFalse(result.safe_zero)
        labels = {item["label"] for item in result.retained_items}
        self.assertTrue(any("Financial" in label for label in labels))
        for item in result.retained_items:
            self.assertEqual(item["period"], "2026-01-31")
            self.assertEqual(item["accession"], "0001108524-26-000001")
            if item["mapping"] == MAPPING_AMBIGUOUS:
                self.assertTrue(item["ambiguity_reason"])
                self.assertFalse(item["included_in_npr_calculation"])
                self.assertFalse(item["included_in_safe_zero_partition"])


if __name__ == "__main__":
    unittest.main()
