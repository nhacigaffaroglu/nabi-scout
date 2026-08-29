from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from services.security_master_contract import (
    INSTRUMENT_EQUITY,
    INSTRUMENT_ETF,
    INSTRUMENT_REIT,
    INSTRUMENT_SUKUK,
    SOURCE_US_LISTING,
)
from services.security_master_listing_ingest import (
    SecurityMasterWriteGuard,
    SecurityMasterWriteGuardError,
    ingest_merged_us_listing_facts,
    planned_listing_source_path,
    scan_persisted_conflicts,
)
from services.security_master_service import SecurityMasterService
from services.universe_discovery_service import ingest_merged_exchange_listings


INGEST = Path("services/security_master_listing_ingest.py")
SCRIPT = Path("scripts/refresh_security_master_listing_facts.py")


def _nasdaq(symbol: str, *, name: str, is_etf: bool = False, exchange: str = "NASDAQ") -> dict:
    return {
        "symbol": symbol,
        "company_name": name,
        "exchange": exchange,
        "is_etf": is_etf,
        "exchange_security_name": name,
    }


def _sec(symbol: str, *, name: str, cik: str) -> dict:
    return {"symbol": symbol, "company_name": name, "cik": cik, "exchange": "NASDAQ"}


class ListingIngestContractTests(unittest.TestCase):
    def test_does_not_call_universe_discovery_ingest(self) -> None:
        source = INGEST.read_text(encoding="utf-8")
        self.assertNotIn("universe_discovery_service", source)
        self.assertNotIn("UniverseExpansionRepository", source)
        self.assertNotIn("FMPClient", source)
        self.assertNotIn("openai", source.lower())
        self.assertIn("merge_exchange_and_sec_listings", source)

    def test_script_does_not_run_participation_or_discovery(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("ingest_merged_exchange_listings", source)
        self.assertNotIn("DailyUniverseExpansion", source)
        self.assertNotIn("FMPClient", source)
        self.assertIn("security_master", source)
        self.assertIn("fetch_us_equity_listing_feeds", source)

    def test_positive_equity_and_etf_exclusion(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        report = ingest_merged_us_listing_facts(
            master,
            nasdaq_rows=[
                _nasdaq("MSFT", name="Microsoft Corporation - Common Stock"),
                _nasdaq("QQQ", name="Invesco QQQ Trust ETF", is_etf=True),
                _nasdaq("ZZZZQ", name="Unknown Warrant"),
            ],
            sec_rows=[
                _sec("MSFT", name="Microsoft Corp", cik="789019"),
                _sec("QQQ", name="Invesco QQQ Trust", cik="106783"),
            ],
        )
        self.assertEqual(report.equity_facts, 1)
        self.assertEqual(report.etf_facts, 1)
        self.assertEqual(report.inserted, 2)
        self.assertEqual(master.resolve_security("MSFT").instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(master.resolve_security("QQQ").instrument_type, INSTRUMENT_ETF)
        self.assertNotEqual(master.resolve_security("QQQ").instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(master.resolve_security("ZZZZQ").instrument_type, "UNKNOWN")
        self.assertGreaterEqual(report.skipped_unproven, 1)

    def test_name_does_not_create_reit_or_sukuk_facts(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        ingest_merged_us_listing_facts(
            master,
            nasdaq_rows=[
                _nasdaq("O", name="Realty Income REIT Common Stock", exchange="NYSE"),
                _nasdaq("BOND1", name="Example Sukuk Note"),
            ],
            sec_rows=[_sec("O", name="Realty Income Corporation", cik="726728")],
        )
        types = {row["instrument_type"] for row in master.repo.list_all()}
        self.assertNotIn(INSTRUMENT_REIT, types)
        self.assertNotIn(INSTRUMENT_SUKUK, types)
        self.assertEqual(master.resolve_security("O").instrument_type, INSTRUMENT_EQUITY)

    def test_identical_replay_is_unchanged_without_timestamp_churn(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        nasdaq = [_nasdaq("AAPL", name="Apple Inc. - Common Stock")]
        sec = [_sec("AAPL", name="Apple Inc.", cik="320193")]
        first = ingest_merged_us_listing_facts(master, nasdaq_rows=nasdaq, sec_rows=sec)
        first_row = master.repo.list_all()[0]
        second = ingest_merged_us_listing_facts(master, nasdaq_rows=nasdaq, sec_rows=sec)
        second_row = master.repo.list_all()[0]
        self.assertEqual(first.inserted, 1)
        self.assertEqual(first.unchanged, 0)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.updated, 0)
        self.assertEqual(second.unchanged, 1)
        self.assertEqual(len(master.repo.list_all()), 1)
        self.assertEqual(first_row["id"], second_row["id"])
        self.assertEqual(first_row["observed_at"], second_row["observed_at"])
        self.assertEqual(first_row["updated_at"], second_row["updated_at"])
        self.assertEqual(first_row["source"], SOURCE_US_LISTING)

    def test_write_guard_blocks_queue_writes(self) -> None:
        class _Table:
            def upsert(self, *args, **kwargs):
                return {"ok": True}

            def select(self, *args, **kwargs):
                return self

        class _Client:
            def table(self, name):
                return _Table()

        guarded = SecurityMasterWriteGuard(_Client())
        guarded.table("security_master").upsert({"identifier": "AAPL"})
        with self.assertRaises(SecurityMasterWriteGuardError):
            guarded.table("universe_expansion_queue").upsert({"symbol": "AAPL"})
        with self.assertRaises(SecurityMasterWriteGuardError):
            guarded.table("investment_candidates").insert({"symbol": "AAPL"})

    def test_planned_source_path_has_no_paid_providers(self) -> None:
        plan = planned_listing_source_path()
        self.assertEqual(plan["planned_FMP_calls"], 0)
        self.assertEqual(plan["planned_LLM_calls"], 0)
        self.assertEqual(plan["expected_universe_queue_writes"], 0)
        self.assertEqual(len(plan["planned_Nasdaq_calls"]), 2)
        self.assertEqual(len(plan["planned_SEC_calls"]), 1)

    def test_conflict_scan_is_in_memory(self) -> None:
        rows = [
            {
                "identifier": "MSFT",
                "identifier_type": "TICKER",
                "instrument_type": INSTRUMENT_EQUITY,
                "source": "alpha",
                "observed_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "identifier": "MSFT",
                "identifier_type": "TICKER",
                "instrument_type": INSTRUMENT_ETF,
                "source": "beta",
                "observed_at": "2026-08-01T00:00:00+00:00",
            },
            {
                "identifier": "AAPL",
                "identifier_type": "TICKER",
                "instrument_type": INSTRUMENT_EQUITY,
                "source": SOURCE_US_LISTING,
                "observed_at": "2026-08-01T00:00:00+00:00",
            },
        ]
        found = scan_persisted_conflicts(rows)
        self.assertEqual([row["identifier"] for row in found], ["MSFT"])
        self.assertEqual(found[0]["limitation"], "SOURCE_CONFLICT")

    def test_discovery_ingest_is_a_separate_function(self) -> None:
        self.assertTrue(inspect.isfunction(ingest_merged_exchange_listings))
        self.assertNotEqual(
            ingest_merged_us_listing_facts.__name__,
            ingest_merged_exchange_listings.__name__,
        )


if __name__ == "__main__":
    unittest.main()
