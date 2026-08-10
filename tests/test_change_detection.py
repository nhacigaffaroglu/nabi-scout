import copy
import json
import unittest
from unittest.mock import MagicMock

from repositories.scan_repository import ScanRepository
from services.change_detection_engine import detect_changes, rank_changes
from services.scan_snapshot import (
    build_scan_snapshot,
    normalize_universe_name,
    sparse_snapshot_from_row,
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


class ChangeDetectionEngineTests(unittest.TestCase):
    def test_no_previous_result(self) -> None:
        result = detect_changes(None, base_snapshot())
        self.assertFalse(result["has_meaningful_change"])
        self.assertTrue(result["no_previous"])
        self.assertEqual(result["change_score"], 0)

    def test_identical_candidates_no_change(self) -> None:
        previous = base_snapshot()
        current = copy.deepcopy(previous)
        result = detect_changes(previous, current)
        self.assertFalse(result["has_meaningful_change"])
        self.assertEqual(result["changes"], [])

    def test_decision_change_is_high(self) -> None:
        previous = base_snapshot(decision_label="İZLE")
        current = base_snapshot(decision_label="ARAŞTIRMA ADAYI")
        result = detect_changes(previous, current)
        self.assertTrue(result["has_meaningful_change"])
        self.assertEqual(result["changes"][0]["severity"], "HIGH")
        self.assertIn("İZLE", result["changes"][0]["message"])

    def test_nabi_small_delta_ignored(self) -> None:
        previous = base_snapshot(nabi_score=71.4)
        current = base_snapshot(nabi_score=73.9)
        result = detect_changes(previous, current)
        nabi_events = [
            item for item in result["changes"] if item["field"] == "nabi_score"
        ]
        self.assertEqual(nabi_events, [])

    def test_nabi_meaningful_delta_detected(self) -> None:
        previous = base_snapshot(nabi_score=71.0)
        current = base_snapshot(nabi_score=75.0)
        result = detect_changes(previous, current)
        nabi_events = [
            item for item in result["changes"] if item["field"] == "nabi_score"
        ]
        self.assertEqual(len(nabi_events), 1)
        self.assertEqual(nabi_events[0]["delta"], 4.0)

    def test_opportunity_threshold(self) -> None:
        previous = base_snapshot(opportunity_score=51.8)
        current = base_snapshot(opportunity_score=59.6)
        result = detect_changes(previous, current)
        events = [
            item
            for item in result["changes"]
            if item["field"] == "opportunity_score"
        ]
        self.assertEqual(len(events), 1)

    def test_confidence_threshold(self) -> None:
        previous = base_snapshot(research_confidence=91.4)
        current = base_snapshot(research_confidence=41.4)
        result = detect_changes(previous, current)
        events = [
            item
            for item in result["changes"]
            if item["field"] == "research_confidence"
        ]
        self.assertEqual(len(events), 1)

    def test_freshness_fresh_to_aging(self) -> None:
        previous = base_snapshot(freshness_status="FRESH")
        current = base_snapshot(freshness_status="AGING")
        result = detect_changes(previous, current)
        event = result["changes"][0]
        self.assertEqual(event["field"], "freshness_status")
        self.assertEqual(event["severity"], "MEDIUM")

    def test_freshness_aging_to_stale(self) -> None:
        previous = base_snapshot(freshness_status="AGING")
        current = base_snapshot(freshness_status="STALE")
        result = detect_changes(previous, current)
        event = result["changes"][0]
        self.assertEqual(event["severity"], "HIGH")

    def test_completeness_change(self) -> None:
        previous = base_snapshot(data_completeness=16.0)
        current = base_snapshot(data_completeness=92.0)
        result = detect_changes(previous, current)
        events = [
            item
            for item in result["changes"]
            if item["field"] == "data_completeness"
        ]
        self.assertEqual(len(events), 1)

    def test_pe_missing_to_available(self) -> None:
        previous = base_snapshot(pe_ratio=None, pe_source="missing")
        current = base_snapshot(pe_ratio=28.1, pe_source="quote")
        result = detect_changes(previous, current)
        self.assertTrue(
            any("artık mevcut" in item["message"] for item in result["changes"])
        )

    def test_pe_available_to_unavailable(self) -> None:
        previous = base_snapshot(pe_ratio=20.0, pe_source="quote")
        current = base_snapshot(pe_ratio=None, pe_source="unavailable")
        result = detect_changes(previous, current)
        self.assertTrue(
            any(
                "geçici olarak erişilemedi" in item["message"]
                for item in result["changes"]
            )
        )

    def test_pe_unavailable_not_valuation_deterioration(self) -> None:
        previous = base_snapshot(pe_ratio=20.0, pe_source="quote")
        current = base_snapshot(pe_ratio=None, pe_source="unavailable")
        result = detect_changes(previous, current)
        valuation_events = [
            item
            for item in result["changes"]
            if item["field"] == "pe_ratio" and item["category"] == "VALUATION"
        ]
        self.assertEqual(valuation_events, [])

    def test_excluded_change(self) -> None:
        previous = base_snapshot(excluded=False)
        current = base_snapshot(excluded=True, status="ELENDİ")
        result = detect_changes(previous, current)
        self.assertEqual(result["changes"][0]["field"], "excluded")
        self.assertEqual(result["changes"][0]["severity"], "HIGH")

    def test_deterministic_change_score(self) -> None:
        previous = base_snapshot(decision_label="İZLE", nabi_score=70.0)
        current = base_snapshot(
            decision_label="ARAŞTIRMA ADAYI",
            nabi_score=75.0,
        )
        first = detect_changes(previous, current)
        second = detect_changes(previous, current)
        self.assertEqual(first, second)
        self.assertEqual(first["change_score"], 45)

    def test_rank_changes_ordering(self) -> None:
        items = [
            {
                "symbol": "BBB",
                "change": {
                    "change_score": 15,
                    "changes": [{"severity": "MEDIUM"}],
                },
            },
            {
                "symbol": "AAA",
                "change": {
                    "change_score": 30,
                    "changes": [{"severity": "HIGH"}],
                },
            },
            {
                "symbol": "CCC",
                "change": {
                    "change_score": 30,
                    "changes": [{"severity": "HIGH"}],
                },
            },
        ]
        ranked = rank_changes(items)
        self.assertEqual([item["symbol"] for item in ranked], ["AAA", "CCC", "BBB"])

    def test_missing_fields_graceful(self) -> None:
        previous = base_snapshot(opportunity_score=None)
        current = base_snapshot(opportunity_score=60.0)
        result = detect_changes(previous, current)
        events = [
            item
            for item in result["changes"]
            if item["field"] == "opportunity_score"
        ]
        self.assertEqual(events, [])

    def test_foreign_issuer_candidate(self) -> None:
        previous = base_snapshot(
            financial_taxonomy=None,
            financial_currency=None,
            data_completeness=16.0,
            status="KISMİ VERİ",
        )
        current = base_snapshot(
            financial_taxonomy="ifrs-full",
            financial_currency="TWD",
            data_completeness=92.0,
            status="TAM VERİ",
        )
        result = detect_changes(previous, current)
        self.assertTrue(result["has_meaningful_change"])

    def test_stale_candidate(self) -> None:
        previous = base_snapshot(
            freshness_status="AGING",
            research_confidence=80.0,
        )
        current = base_snapshot(
            freshness_status="STALE",
            research_confidence=41.4,
        )
        result = detect_changes(previous, current)
        self.assertTrue(
            any(item["field"] == "freshness_status" for item in result["changes"])
        )

    def test_legacy_sparse_completeness_message(self) -> None:
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
        result = detect_changes(previous, current)
        self.assertTrue(
            any(
                "Veri kapsamı değişti" in item["message"]
                for item in result["changes"]
            )
        )
        self.assertFalse(
            any(item["field"] == "decision_label" for item in result["changes"])
        )


class ScanSnapshotTests(unittest.TestCase):
    def test_normalize_universe_name(self) -> None:
        self.assertEqual(
            normalize_universe_name("Teknoloji 10 [1-3]"),
            "Teknoloji 10",
        )
        self.assertEqual(
            normalize_universe_name("Teknoloji 10 [4-6]"),
            "Teknoloji 10",
        )

    def test_snapshot_serialization(self) -> None:
        result = {
            "symbol": "MSFT",
            "excluded": False,
            "status": "TAM VERİ",
            "endpoint_status": {"fmp_quote": "OK"},
            "candidate": base_snapshot(symbol="MSFT"),
        }
        snapshot = build_scan_snapshot(result)
        json.dumps(snapshot)
        self.assertEqual(snapshot["symbol"], "MSFT")
        self.assertEqual(snapshot["_comparison_source"], "snapshot")
        self.assertNotIn("scanner_version", snapshot)


class ScanRepositoryTests(unittest.TestCase):
    def _repo(self, rows):
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table

        def chain(methods):
            mock = MagicMock()
            for name in methods:
                setattr(mock, name, MagicMock(return_value=mock))
            mock.execute.return_value = MagicMock(data=rows)
            return mock

        table.select.return_value = chain([
            "eq",
            "neq",
            "order",
            "limit",
            "execute",
        ])
        return ScanRepository(client)

    def test_current_run_exclusion_query(self) -> None:
        repo = ScanRepository(MagicMock())
        client = repo.client
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.neq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value = MagicMock(data=[])

        repo.get_previous_snapshot("MSFT", "run-current", "Teknoloji 10 [1-3]")
        query.neq.assert_called_with("scan_run_id", "run-current")

    def test_same_universe_preference(self) -> None:
        rows = [
            {
                "symbol": "MSFT",
                "candidate_snapshot": base_snapshot(symbol="MSFT", nabi_score=60.0),
                "scan_runs": {"universe_name": "Teknoloji 10 [1-5]", "status": "COMPLETED"},
            },
            {
                "symbol": "MSFT",
                "candidate_snapshot": base_snapshot(symbol="MSFT", nabi_score=40.0),
                "scan_runs": {"universe_name": "Diğer Evren [1-3]", "status": "COMPLETED"},
            },
        ]
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.neq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value = MagicMock(data=rows)

        repo = ScanRepository(client)
        snapshot = repo.get_previous_snapshot(
            "MSFT",
            "run-current",
            "Teknoloji 10 [1-3]",
        )
        self.assertEqual(snapshot["nabi_score"], 60.0)

    def test_global_symbol_fallback(self) -> None:
        rows = [
            {
                "symbol": "MSFT",
                "candidate_snapshot": base_snapshot(symbol="MSFT", nabi_score=55.0),
                "scan_runs": {"universe_name": "Diğer Evren [1-3]", "status": "COMPLETED"},
            },
        ]
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.neq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value = MagicMock(data=rows)

        repo = ScanRepository(client)
        snapshot = repo.get_previous_snapshot(
            "MSFT",
            "run-current",
            "Teknoloji 10 [1-3]",
        )
        self.assertEqual(snapshot["nabi_score"], 55.0)

    def test_legacy_sparse_fallback(self) -> None:
        rows = [
            {
                "symbol": "AAPL",
                "status": "KISMİ VERİ",
                "nabi_score": 26.1,
                "data_completeness": 12.0,
                "endpoint_status": {},
                "candidate_snapshot": None,
                "scan_runs": {"universe_name": "Teknoloji 10 [1-5]", "status": "COMPLETED"},
            },
        ]
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        query = MagicMock()
        table.select.return_value = query
        query.eq.return_value = query
        query.neq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value = MagicMock(data=rows)

        repo = ScanRepository(client)
        snapshot = repo.get_previous_snapshot("AAPL", "run-current", "Teknoloji 10 [1-3]")
        self.assertEqual(snapshot["_comparison_source"], "legacy_sparse")
        self.assertEqual(snapshot["data_completeness"], 12.0)

    def test_add_result_falls_back_without_snapshot_column(self) -> None:
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        insert_query = MagicMock()
        table.insert.return_value = insert_query
        insert_query.execute.side_effect = [
            Exception("Could not find the 'candidate_snapshot' column"),
            MagicMock(data=[{"id": "1"}]),
        ]

        repo = ScanRepository(client)
        repo.add_result(
            "run-1",
            {
                "symbol": "MSFT",
                "status": "TAM VERİ",
                "excluded": False,
                "endpoint_status": {},
                "errors": [],
                "candidate": base_snapshot(symbol="MSFT"),
            },
        )
        self.assertEqual(table.insert.call_count, 2)
        second_payload = table.insert.call_args_list[1].args[0]
        self.assertNotIn("candidate_snapshot", second_payload)


if __name__ == "__main__":
    unittest.main()
