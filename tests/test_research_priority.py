import unittest
from unittest.mock import MagicMock

from services.change_detection_engine import detect_changes
from services.research_monitor_service import build_priority_entries
from services.research_priority_engine import (
    compute_research_priority,
    rank_priority_entries,
)


def base_snapshot(**overrides):
    snapshot = {
        "symbol": "TEST",
        "status": "TAM VERİ",
        "excluded": False,
        "security_type": "COMMON",
        "issuer_category": "OPERATING_COMPANY",
        "nabi_score": 70.0,
        "decision_label": "İZLE",
        "opportunity_score": 50.0,
        "conviction_score": 60.0,
        "research_confidence": 80.0,
        "score_confidence": "YÜKSEK",
        "data_completeness": 90.0,
        "freshness_status": "FRESH",
        "freshness_label": "Güncel",
        "period_age_days": 100,
        "financial_period_end": "2025-12-31",
        "pe_ratio": 20.0,
        "pe_source": "quote",
        "roic": 15.0,
        "revenue_growth_1y": 10.0,
        "revenue_cagr_3y": 12.0,
        "free_cash_flow_margin": 11.0,
        "financial_taxonomy": "us-gaap",
        "financial_currency": "USD",
        "fmp_source_status": {},
        "endpoint_status": {},
        "_comparison_source": "snapshot",
    }
    snapshot.update(overrides)
    return snapshot


def base_candidate(**overrides):
    candidate = {
        "id": "cand-1",
        "symbol": "TEST",
        "company_name": "Test Co",
        "nabi_score": 72.0,
        "decision_label": "ARAŞTIRMA ADAYI",
        "opportunity_score": 55.0,
        "conviction_score": 62.0,
        "research_confidence": 78.0,
        "freshness_status": "FRESH",
        "data_completeness": 90.0,
    }
    candidate.update(overrides)
    return candidate


class ResearchPriorityEngineTests(unittest.TestCase):
    def test_research_candidate_baseline(self) -> None:
        result = compute_research_priority(base_candidate())
        self.assertEqual(result["components"]["decision_label"], 25.0)
        self.assertIn("ARAŞTIRMA ADAYI", result["reasons"])

    def test_high_priority_candidate(self) -> None:
        result = compute_research_priority(
            base_candidate(
                decision_label="YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI",
                conviction_score=72.0,
            ),
            recent_change={
                "change_score": 30,
                "changes": [{"severity": "HIGH", "message": "Karar değişti"}],
            },
            is_user_watchlist=True,
        )
        self.assertGreaterEqual(result["priority_score"], 70)
        self.assertEqual(result["priority_label"], "YÜKSEK")

    def test_stable_high_nabi_not_automatically_max(self) -> None:
        result = compute_research_priority(
            base_candidate(
                nabi_score=92.0,
                decision_label="İZLE",
                opportunity_score=50.0,
                conviction_score=55.0,
                research_confidence=80.0,
            )
        )
        self.assertLess(result["priority_score"], 70)
        self.assertNotIn("nabi_score", result["components"])

    def test_high_recent_change(self) -> None:
        result = compute_research_priority(
            base_candidate(),
            recent_change={
                "change_score": 30,
                "changes": [{"severity": "HIGH", "message": "Karar değişti"}],
            },
        )
        self.assertEqual(result["components"]["recent_change"], 25.0)

    def test_medium_recent_change(self) -> None:
        result = compute_research_priority(
            base_candidate(),
            recent_change={
                "change_score": 18,
                "changes": [{"severity": "MEDIUM", "message": "Veri kapsamı değişti"}],
            },
        )
        self.assertEqual(result["components"]["recent_change"], 12.0)

    def test_first_seen(self) -> None:
        result = compute_research_priority(
            base_candidate(),
            is_first_seen=True,
        )
        self.assertEqual(result["components"]["first_seen"], 8.0)
        self.assertIn("Yeni takip edilen şirket", result["reasons"])

    def test_watchlist_boost(self) -> None:
        result = compute_research_priority(
            base_candidate(),
            is_user_watchlist=True,
        )
        self.assertEqual(result["components"]["user_watchlist"], 10.0)

    def test_stale_review_boost(self) -> None:
        result = compute_research_priority(
            base_candidate(freshness_status="STALE"),
        )
        self.assertEqual(result["components"]["freshness_status"], 10.0)
        self.assertIn(
            "Finansal veri güncel değil — doğrulama gerekir",
            result["reasons"],
        )

    def test_low_confidence_review_boost(self) -> None:
        result = compute_research_priority(
            base_candidate(research_confidence=42.0),
        )
        self.assertEqual(result["components"]["research_confidence"], 5.0)
        self.assertIn(
            "Veri güveni düşük — ek doğrulama gerekir",
            result["reasons"],
        )

    def test_api_outage_not_fundamental_reason(self) -> None:
        previous = base_snapshot(pe_ratio=20.0, pe_source="quote")
        current = base_snapshot(pe_ratio=None, pe_source="unavailable")
        change = detect_changes(previous, current)
        result = compute_research_priority(
            base_candidate(),
            recent_change=change,
        )
        reasons = " ".join(result["reasons"])
        self.assertNotIn("değerleme", reasons.lower())
        self.assertTrue(
            any("erişilemedi" in item["message"] for item in change["changes"])
            or any("geçici" in reason for reason in result["reasons"])
        )

    def test_opportunity_contribution_bounded(self) -> None:
        low = compute_research_priority(
            base_candidate(opportunity_score=52.0),
        )
        high = compute_research_priority(
            base_candidate(opportunity_score=98.0),
        )
        self.assertLessEqual(high["components"].get("opportunity_score", 0), 8.0)
        self.assertGreater(
            high["components"].get("opportunity_score", 0),
            low["components"].get("opportunity_score", 0),
        )

    def test_conviction_contribution(self) -> None:
        result = compute_research_priority(
            base_candidate(conviction_score=74.0),
        )
        self.assertEqual(result["components"]["conviction_score"], 5.0)

    def test_deterministic(self) -> None:
        candidate = base_candidate()
        change = {
            "change_score": 12,
            "changes": [{"severity": "MEDIUM", "message": "Veri kapsamı değişti"}],
        }
        first = compute_research_priority(
            candidate,
            recent_change=change,
            is_user_watchlist=True,
        )
        second = compute_research_priority(
            candidate,
            recent_change=change,
            is_user_watchlist=True,
        )
        self.assertEqual(first, second)

    def test_ordering(self) -> None:
        entries = [
            {
                "priority_score": 55.0,
                "candidate": base_candidate(symbol="BBB", conviction_score=60.0),
                "recent_change": {"change_score": 10},
            },
            {
                "priority_score": 55.0,
                "candidate": base_candidate(symbol="AAA", conviction_score=80.0),
                "recent_change": {"change_score": 10},
            },
            {
                "priority_score": 70.0,
                "candidate": base_candidate(symbol="CCC"),
                "recent_change": {"change_score": 5},
            },
        ]
        ranked = rank_priority_entries(entries)
        self.assertEqual(
            [item["candidate"]["symbol"] for item in ranked],
            ["CCC", "AAA", "BBB"],
        )

    def test_missing_fields_graceful(self) -> None:
        result = compute_research_priority({})
        self.assertGreaterEqual(result["priority_score"], 0)
        self.assertLessEqual(result["priority_score"], 100)
        self.assertEqual(result["priority_label"], "DÜŞÜK")

    def test_foreign_issuer(self) -> None:
        result = compute_research_priority(
            base_candidate(
                financial_taxonomy="ifrs-full",
                financial_currency="TWD",
                data_completeness=92.0,
                freshness_status="FRESH",
            )
        )
        self.assertIn("priority_score", result)

    def test_stale_issuer(self) -> None:
        result = compute_research_priority(
            base_candidate(
                freshness_status="STALE",
                research_confidence=41.0,
            )
        )
        self.assertGreaterEqual(result["priority_score"], 15.0)


class ResearchPriorityIntegrationTests(unittest.TestCase):
    def test_previous_current_change_priority(self) -> None:
        previous = base_snapshot(decision_label="İZLE")
        current = base_snapshot(decision_label="ARAŞTIRMA ADAYI")
        change = detect_changes(previous, current)
        result = compute_research_priority(
            base_candidate(decision_label="ARAŞTIRMA ADAYI"),
            recent_change=change,
        )
        self.assertGreaterEqual(result["components"].get("recent_change", 0), 25.0)

    def test_watchlist_plus_change(self) -> None:
        change = {
            "change_score": 30,
            "changes": [{"severity": "HIGH", "message": "Karar değişti"}],
        }
        result = compute_research_priority(
            base_candidate(),
            recent_change=change,
            is_user_watchlist=True,
        )
        self.assertEqual(result["components"]["user_watchlist"], 10.0)
        self.assertEqual(result["components"]["recent_change"], 25.0)

    def test_fmp_unavailable(self) -> None:
        previous = base_snapshot(pe_ratio=20.0, pe_source="quote")
        current = base_snapshot(pe_ratio=None, pe_source="unavailable")
        change = detect_changes(previous, current)
        result = compute_research_priority(
            base_candidate(),
            recent_change=change,
        )
        valuation_reasons = [
            reason
            for reason in result["reasons"]
            if "değerleme" in reason.lower()
        ]
        self.assertEqual(valuation_reasons, [])

    def test_legacy_sparse(self) -> None:
        from services.scan_snapshot import sparse_snapshot_from_row

        previous = sparse_snapshot_from_row({
            "symbol": "AAPL",
            "status": "KISMİ VERİ",
            "nabi_score": 26.1,
            "data_completeness": 12.0,
            "endpoint_status": {},
        })
        current = base_snapshot(
            symbol="AAPL",
            data_completeness=96.0,
            status="TAM VERİ",
        )
        change = detect_changes(previous, current)
        result = compute_research_priority(
            base_candidate(symbol="AAPL", data_completeness=96.0),
            recent_change=change,
        )
        self.assertFalse(
            any("Karar etiketi" in reason for reason in result["reasons"])
        )

    def test_no_previous(self) -> None:
        change = detect_changes(None, base_snapshot())
        result = compute_research_priority(
            base_candidate(),
            recent_change=change,
            is_first_seen=True,
        )
        self.assertEqual(result["components"].get("recent_change", 0), 0)
        self.assertEqual(result["components"]["first_seen"], 8.0)

    def test_build_priority_entries_batch(self) -> None:
        scan_repo = MagicMock()
        scan_repo.get_latest_scan_rows_for_symbols.return_value = {}
        scan_repo.row_to_snapshot.side_effect = lambda row: row.get("snapshot")
        scan_repo.get_latest_scan_row.return_value = None

        entries = build_priority_entries(
            [
                base_candidate(symbol="AAA", id="1"),
                base_candidate(symbol="BBB", id="2"),
            ],
            scan_repo=scan_repo,
            watched_candidate_ids={"2"},
        )
        self.assertEqual(len(entries), 2)
        watched_entry = next(
            item for item in entries if item["candidate"]["symbol"] == "BBB"
        )
        self.assertEqual(watched_entry["components"].get("user_watchlist"), 10.0)


if __name__ == "__main__":
    unittest.main()
