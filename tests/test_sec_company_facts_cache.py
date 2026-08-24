from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from repositories.sec_company_facts_cache import SecCompanyFactsCache
from services.sec_company_facts_evidence import (
    SOURCE_SEC_COMPANY_FACTS,
    SecCompanyFactsCacheError,
    digest_company_facts_payload,
)
from services.sec_financial_client import SECFinancialClient
from services.sec_participation_evidence_population import (
    resolve_assessed_equity_population,
)
from services.sec_participation_evidence_refresh import (
    fetch_sec_evidence,
    plan_sec_evidence_refresh,
)
from services.universe_expansion_contract import (
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)


def _facts(assets: int = 100) -> dict:
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                                "val": 50,
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "end": "2025-12-31",
                                "val": assets,
                                "filed": "2026-02-01",
                            }
                        ]
                    }
                },
            }
        }
    }


def _snapshot(symbol: str, cik: str, status: str = "Kontrol Et") -> dict:
    return {
        "symbol": symbol,
        "status": status,
        "source_evidence": {"cik": cik, "provider": "SEC"},
        "assessment_payload": {
            "source_evidence": {"cik": cik, "provider": "SEC"},
            "financial_inputs": {"total_assets": 1},
        },
    }


class DigestAndCacheTests(unittest.TestCase):
    def test_store_hit_miss_and_duplicate_digest(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            self.assertIsNone(cache.get_latest(symbol="AAPL"))
            first, created = cache.store_if_new(
                symbol="AAPL",
                cik="320193",
                raw_payload=_facts(10),
            )
            self.assertTrue(created)
            self.assertEqual(first.source, SOURCE_SEC_COMPANY_FACTS)
            self.assertTrue(first.content_digest)
            cache.verify_digest(first.content_digest)
            second, created_again = cache.store_if_new(
                symbol="AAPL",
                cik="320193",
                raw_payload=_facts(10),
            )
            self.assertFalse(created_again)
            self.assertEqual(first.content_digest, second.content_digest)
            objects = list((Path(tmp) / "objects").glob("*.json"))
            self.assertEqual(len(objects), 1)
            latest = cache.get_latest(symbol="AAPL")
            self.assertIsNotNone(latest)
            self.assertEqual(latest.content_digest, first.content_digest)

    def test_changed_payload_creates_new_version(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            first, _ = cache.store_if_new(
                symbol="AAPL",
                cik="320193",
                raw_payload=_facts(10),
            )
            second, created = cache.store_if_new(
                symbol="AAPL",
                cik="320193",
                raw_payload=_facts(11),
            )
            self.assertTrue(created)
            self.assertNotEqual(first.content_digest, second.content_digest)
            self.assertEqual(cache.get_latest(symbol="AAPL").content_digest, second.content_digest)
            self.assertIsNotNone(cache.get_by_digest(first.content_digest))
            self.assertEqual(len(list((Path(tmp) / "objects").glob("*.json"))), 2)

    def test_corrupt_digest_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            evidence, _ = cache.store_if_new(
                symbol="AAPL",
                cik="320193",
                raw_payload=_facts(10),
            )
            path = Path(tmp) / "objects" / f"{evidence.content_digest}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["raw_payload"]["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = 999
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(SecCompanyFactsCacheError):
                cache.get_by_digest(evidence.content_digest)

    def test_replay_extracts_without_provider_call(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            evidence, _ = cache.store_if_new(
                symbol="AAPL",
                cik="320193",
                raw_payload=_facts(359),
            )
            extracted = cache.replay(evidence)
            self.assertEqual(extracted["total_assets"], 359)
            self.assertEqual(extracted["balance_sheet_period_end"], "2025-12-31")

    def test_digest_is_payload_identity(self) -> None:
        self.assertEqual(
            digest_company_facts_payload(_facts(1)),
            digest_company_facts_payload(_facts(1)),
        )
        self.assertNotEqual(
            digest_company_facts_payload(_facts(1)),
            digest_company_facts_payload(_facts(2)),
        )


class PopulationIdentityTests(unittest.TestCase):
    def test_excludes_catalog_pending_and_unassessed(self) -> None:
        population = resolve_assessed_equity_population(
            queue_rows=[
                {"symbol": "AAPL", "status": EXPANSION_STATUS_COMPLETED},
                {"symbol": "ODFL", "status": EXPANSION_STATUS_PENDING},
                {"symbol": "SPUS", "status": EXPANSION_STATUS_COMPLETED},
                {"symbol": "CRM", "status": EXPANSION_STATUS_RETRYABLE},
            ],
            snapshots_by_symbol={
                "AAPL": _snapshot("AAPL", "320193", "Uygun Değil"),
                "CRM": _snapshot("CRM", "1108524", "Uygun"),
                "SPUS": _snapshot("SPUS", "1", "Uygun"),
            },
        )
        self.assertEqual(population.symbols, ("AAPL", "CRM"))
        self.assertEqual(population.pending_excluded, ("ODFL",))
        self.assertEqual(population.catalog_excluded, ("SPUS",))
        self.assertEqual(population.fetchable_ciks, ("0000320193", "0001108524"))

    def test_cik_conflict_and_duplicate_are_not_fetchable(self) -> None:
        population = resolve_assessed_equity_population(
            queue_rows=[
                {"symbol": "AAA", "status": EXPANSION_STATUS_COMPLETED},
                {"symbol": "BBB", "status": EXPANSION_STATUS_COMPLETED},
                {"symbol": "CCC", "status": EXPANSION_STATUS_COMPLETED},
            ],
            snapshots_by_symbol={
                "AAA": _snapshot("AAA", "111"),
                "BBB": _snapshot("BBB", "111"),
                "CCC": _snapshot("CCC", "222"),
            },
            candidates_by_symbol={"CCC": {"symbol": "CCC", "cik": "333"}},
        )
        by_symbol = {item.symbol: item for item in population.assessed}
        self.assertFalse(by_symbol["AAA"].fetchable)
        self.assertFalse(by_symbol["BBB"].fetchable)
        self.assertFalse(by_symbol["CCC"].fetchable)
        self.assertIn("0000000111", population.duplicate_ciks)
        self.assertEqual(population.cik_conflicts, ("CCC",))

    def test_missing_cik_is_reported(self) -> None:
        population = resolve_assessed_equity_population(
            queue_rows=[{"symbol": "ZZZ", "status": EXPANSION_STATUS_COMPLETED}],
            snapshots_by_symbol={"ZZZ": {"symbol": "ZZZ", "status": "Kontrol Et"}},
        )
        self.assertEqual(population.missing_cik, ("ZZZ",))
        self.assertEqual(population.fetchable, ())


class RefreshPlanAndFetchTests(unittest.TestCase):
    def test_plan_counts_misses_without_provider(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            cache.store_if_new(symbol="AAPL", cik="320193", raw_payload=_facts(1))
            plan = plan_sec_evidence_refresh(
                queue_rows=[
                    {"symbol": "AAPL", "status": EXPANSION_STATUS_COMPLETED},
                    {"symbol": "CRM", "status": EXPANSION_STATUS_COMPLETED},
                ],
                snapshots_by_symbol={
                    "AAPL": _snapshot("AAPL", "320193"),
                    "CRM": _snapshot("CRM", "1108524"),
                },
                cache=cache,
            )
            self.assertEqual(plan.cache_hits, ("AAPL",))
            self.assertEqual(plan.cache_misses, ("CRM",))
            self.assertEqual(plan.expected_sec_calls, 1)

    def test_fetch_writes_cache_only_and_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            plan = plan_sec_evidence_refresh(
                queue_rows=[{"symbol": "CRM", "status": EXPANSION_STATUS_COMPLETED}],
                snapshots_by_symbol={"CRM": _snapshot("CRM", "1108524")},
                cache=cache,
            )
            fetcher = MagicMock(return_value=_facts(88))
            first = fetch_sec_evidence(plan, fetcher=fetcher, cache=cache)
            self.assertEqual(first.sec_calls, 1)
            self.assertEqual(first.stored, ("CRM",))
            replayed_plan = plan_sec_evidence_refresh(
                queue_rows=[{"symbol": "CRM", "status": EXPANSION_STATUS_COMPLETED}],
                snapshots_by_symbol={"CRM": _snapshot("CRM", "1108524")},
                cache=cache,
            )
            second = fetch_sec_evidence(replayed_plan, fetcher=fetcher, cache=cache)
            self.assertEqual(second.sec_calls, 0)
            self.assertEqual(fetcher.call_count, 1)
            extracted = cache.replay(cache.get_latest(symbol="CRM"))
            self.assertEqual(extracted["total_assets"], 88)


class FirewallTests(unittest.TestCase):
    def test_cache_modules_do_not_import_forbidden_surfaces(self) -> None:
        import services.sec_company_facts_evidence as evidence
        import services.sec_participation_evidence_population as population
        import services.sec_participation_evidence_refresh as refresh
        import repositories.sec_company_facts_cache as cache_mod

        forbidden = (
            "fmp_client",
            "scanner_v",
            "research_intelligence",
            "nabi_score_v4",
            "decision_engine",
            "streamlit",
        )
        for module in (evidence, population, refresh, cache_mod):
            source = inspect.getsource(module)
            for token in forbidden:
                self.assertNotIn(token, source)
        self.assertNotIn("company_facts(", inspect.getsource(cache_mod.SecCompanyFactsCache.replay))


class ExtractorStillIndependentTests(unittest.TestCase):
    def test_extractor_does_not_read_cache(self) -> None:
        source = inspect.getsource(SECFinancialClient.extract_financials)
        self.assertNotIn("SecCompanyFactsCache", source)
        self.assertNotIn("sec_company_facts_cache", source)


if __name__ == "__main__":
    unittest.main()
