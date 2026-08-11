import unittest

from services.signal_classification_service import (
    DIRECTION_CHANGE,
    DIRECTION_DEGRADATION,
    DIRECTION_RECOVERY,
    SIGNAL_FAMILY_DATA_QUALITY,
    SIGNAL_FAMILY_DISCOVERY,
    SIGNAL_FAMILY_RESEARCH,
    SIGNAL_FAMILY_UNKNOWN,
    SignalSummary,
    classify_data_quality_direction,
    classify_event,
    classify_monitor_entry,
    summarize_data_quality_update,
)


class ClassifyEventTests(unittest.TestCase):
    def test_decision_is_research(self) -> None:
        self.assertEqual(
            classify_event({"category": "DECISION", "field": "decision_label"}),
            SIGNAL_FAMILY_RESEARCH,
        )

    def test_score_is_research(self) -> None:
        self.assertEqual(
            classify_event({"category": "SCORE", "field": "nabi_score"}),
            SIGNAL_FAMILY_RESEARCH,
        )

    def test_growth_is_research(self) -> None:
        self.assertEqual(
            classify_event({"category": "GROWTH", "field": "revenue_growth_1y"}),
            SIGNAL_FAMILY_RESEARCH,
        )

    def test_quality_is_research(self) -> None:
        self.assertEqual(
            classify_event({"category": "QUALITY", "field": "roic"}),
            SIGNAL_FAMILY_RESEARCH,
        )

    def test_valuation_is_research(self) -> None:
        self.assertEqual(
            classify_event({"category": "VALUATION", "field": "pe_ratio", "old": 20, "new": 25}),
            SIGNAL_FAMILY_RESEARCH,
        )

    def test_completeness_is_data_quality(self) -> None:
        self.assertEqual(
            classify_event({"category": "COMPLETENESS", "field": "data_completeness"}),
            SIGNAL_FAMILY_DATA_QUALITY,
        )

    def test_availability_is_data_quality(self) -> None:
        self.assertEqual(
            classify_event({"category": "AVAILABILITY", "field": "pe_source"}),
            SIGNAL_FAMILY_DATA_QUALITY,
        )

    def test_freshness_is_data_quality(self) -> None:
        self.assertEqual(
            classify_event({"category": "FRESHNESS", "field": "freshness_status"}),
            SIGNAL_FAMILY_DATA_QUALITY,
        )

    def test_data_status_is_data_quality(self) -> None:
        self.assertEqual(
            classify_event({"category": "DATA_STATUS", "field": "status"}),
            SIGNAL_FAMILY_DATA_QUALITY,
        )

    def test_research_confidence_is_data_quality(self) -> None:
        self.assertEqual(
            classify_event({"category": "CONFIDENCE", "field": "research_confidence"}),
            SIGNAL_FAMILY_DATA_QUALITY,
        )

    def test_score_confidence_is_data_quality(self) -> None:
        self.assertEqual(
            classify_event({"category": "CONFIDENCE", "field": "score_confidence"}),
            SIGNAL_FAMILY_DATA_QUALITY,
        )

    def test_malformed_event_is_unknown(self) -> None:
        self.assertEqual(classify_event(None), SIGNAL_FAMILY_UNKNOWN)
        self.assertEqual(classify_event("bad"), SIGNAL_FAMILY_UNKNOWN)

    def test_missing_category_known_field(self) -> None:
        self.assertEqual(
            classify_event({"field": "decision_label"}),
            SIGNAL_FAMILY_RESEARCH,
        )


class DirectionTests(unittest.TestCase):
    def test_completeness_increase_recovery(self) -> None:
        direction = classify_data_quality_direction({
            "field": "data_completeness",
            "category": "COMPLETENESS",
            "old": 12,
            "new": 76,
            "delta": 64,
        })
        self.assertEqual(direction, DIRECTION_RECOVERY)

    def test_completeness_decrease_degradation(self) -> None:
        direction = classify_data_quality_direction({
            "field": "data_completeness",
            "category": "COMPLETENESS",
            "old": 76,
            "new": 12,
            "delta": -64,
        })
        self.assertEqual(direction, DIRECTION_DEGRADATION)

    def test_freshness_worsening_degradation(self) -> None:
        direction = classify_data_quality_direction({
            "field": "freshness_status",
            "category": "FRESHNESS",
            "old": "FRESH",
            "new": "STALE",
        })
        self.assertEqual(direction, DIRECTION_DEGRADATION)

    def test_freshness_recovery(self) -> None:
        direction = classify_data_quality_direction({
            "field": "freshness_status",
            "category": "FRESHNESS",
            "old": "STALE",
            "new": "FRESH",
        })
        self.assertEqual(direction, DIRECTION_RECOVERY)

    def test_ambiguous_direction_change(self) -> None:
        direction = classify_data_quality_direction({"field": "status", "category": "DATA_STATUS"})
        self.assertEqual(direction, DIRECTION_CHANGE)


class MonitorEntryTests(unittest.TestCase):
    def test_first_seen_discovery(self) -> None:
        summary = classify_monitor_entry({"is_first_seen_in_window": True, "events": []})
        self.assertIn(SIGNAL_FAMILY_DISCOVERY, summary.families)

    def test_mixed_research_and_data_quality(self) -> None:
        summary = classify_monitor_entry({
            "events": [
                {"category": "DECISION", "field": "decision_label", "message": "Karar değişti"},
                {"category": "COMPLETENESS", "field": "data_completeness", "old": 12, "new": 76},
            ],
        })
        self.assertTrue(summary.is_research_actionable)
        self.assertIn(SIGNAL_FAMILY_RESEARCH, summary.families)
        self.assertIn(SIGNAL_FAMILY_DATA_QUALITY, summary.families)
        self.assertFalse(summary.is_data_quality_only)

    def test_data_quality_only_not_actionable(self) -> None:
        summary = classify_monitor_entry({
            "events": [{
                "category": "COMPLETENESS",
                "field": "data_completeness",
                "old": 12,
                "new": 76,
            }],
        })
        self.assertFalse(summary.is_research_actionable)
        self.assertTrue(summary.is_data_quality_only)

    def test_unknown_only_not_actionable(self) -> None:
        summary = classify_monitor_entry({"events": [{"foo": "bar"}]})
        self.assertFalse(summary.is_research_actionable)

    def test_recovery_summary_wording(self) -> None:
        summary = summarize_data_quality_update({
            "events": [{
                "field": "data_completeness",
                "category": "COMPLETENESS",
                "old": 12,
                "new": 76,
            }],
        }, direction=DIRECTION_RECOVERY)
        self.assertIn("Veri tamlığı yeniden yükseldi", summary)
        self.assertNotIn("iyileşti.", summary.replace("Veri tamlığı yeniden yükseldi.", ""))


if __name__ == "__main__":
    unittest.main()
