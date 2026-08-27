from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.daily_universe_expansion_service import DailyUniverseExpansionService
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.scan_universe_service import filter_scanner_eligible_rows
from services.universe_discovery_listings import (
    merge_exchange_and_sec_listings,
    select_us_equity_discovery_candidates,
)
from services.universe_discovery_metrics import collect_universe_discovery_metrics
from services.universe_discovery_service import ingest_us_equity_listings
from services.universe_expansion_contract import (
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
    STOP_REASON_SAFETY_CAP,
)
from services.universe_expansion_onboarding_service import OnboardingResult
from services.universe_expansion_seed_service import seed_universe_expansion_queue
from services.universe_external_signal import propose_symbols_from_external_signal
from services.universe_listing_identity import (
    excluded_instrument_reason,
    listing_identity,
    listing_priority,
)


def _now() -> datetime:
    return datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)


def _listing(
    symbol: str,
    *,
    name: str | None = None,
    exchange: str = "NASDAQ",
    cik: str | None = "100",
    is_etf: bool = False,
    sector: str | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "company_name": name or symbol,
        "exchange": exchange,
        "cik": cik,
        "is_etf": is_etf,
        "sector": sector,
    }


def _ok(symbol: str) -> OnboardingResult:
    return OnboardingResult(
        symbol=symbol,
        success=True,
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        snapshot_saved=True,
        candidate_upserted=True,
    )


class IdentityAndExclusionTests(unittest.TestCase):
    def test_class_share_dot_and_hyphen_share_identity(self) -> None:
        self.assertEqual(listing_identity("brk.b"), "BRK-B")
        self.assertEqual(listing_identity("BRK-B"), "BRK-B")
        self.assertEqual(listing_identity("aapl"), "AAPL")

    def test_excluded_instrument_types_stay_out(self) -> None:
        cases = (
            ("AAPL-WT", "Apple Warrant", False, "non_common_suffix"),
            ("ABC^", "ABC Preferred", False, "non_common_symbol"),
            ("XYZ-U", "XYZ Units", False, "non_common_suffix"),
            ("RIGHTS", "Acme Rights", False, "excluded_name"),
            ("SPACX", "Blank Check Acquisition Corp", False, "excluded_name"),
            ("TQQQ", "ProShares UltraPro QQQ 3X", True, "etf"),
            ("SOXL", "Direxion Daily Semiconductor Bull 3X Shares", False, "excluded_name"),
            ("HLAL", "Wahed FTSE USA Shariah ETF", False, "catalog_etf"),
        )
        for symbol, name, is_etf, expected in cases:
            reason = excluded_instrument_reason(
                symbol=symbol,
                company_name=name,
                is_etf=is_etf,
            )
            self.assertEqual(reason, expected, msg=symbol)

    def test_ordinary_equities_remain_eligible_regardless_of_sector(self) -> None:
        for symbol, name, sector in (
            ("JPM", "JPMorgan Chase & Co", "Financials"),
            ("XOM", "Exxon Mobil Corporation", "Energy"),
            ("UNH", "UnitedHealth Group Incorporated", "Health Care"),
            ("BA", "Boeing Company", "Industrials"),
            ("TXG", "10x Genomics Inc", "Health Care"),
        ):
            self.assertIsNone(
                excluded_instrument_reason(symbol=symbol, company_name=name, is_etf=False),
                msg=symbol,
            )
            rows = select_us_equity_discovery_candidates(
                [_listing(symbol, name=name, sector=sector, exchange="NYSE", cik="1")]
            )
            self.assertEqual([row.symbol for row in rows], [symbol])

    def test_united_name_is_not_treated_as_unit(self) -> None:
        self.assertIsNone(
            excluded_instrument_reason(
                symbol="UAL",
                company_name="United Airlines Holdings Inc",
                is_etf=False,
            )
        )


class LargeDiscoveryIngestTests(unittest.TestCase):
    def test_large_discovery_input_dedupes_deterministically(self) -> None:
        listings = []
        for index in range(300):
            listings.append(
                _listing(f"EQ{index:03d}", exchange="NYSE" if index % 2 == 0 else "NASDAQ")
            )
        listings.extend(listings[:80])
        listings.append(_listing("brk.b", name="Berkshire Hathaway", exchange="NYSE", cik="1067983"))
        listings.append(_listing("BRK-B", name="Berkshire Hathaway", exchange="NYSE", cik="1067983"))
        repo = UniverseExpansionRepository()
        report = ingest_us_equity_listings(
            repo,
            listings,
            discovery_capacity=8000,
            max_new_symbols_per_ingest=8000,
        )
        symbols = [row["symbol"] for row in repo.list_all()]
        self.assertEqual(len(symbols), len(set(symbols)))
        self.assertEqual(symbols.count("BRK-B"), 1)
        self.assertNotIn("BRK.B", symbols)
        self.assertEqual(report.inserted, 301)
        self.assertGreater(report.skipped_duplicate_input, 0)
        nyse_before_nasdaq = [
            row["symbol"]
            for row in sorted(repo.list_all(), key=lambda item: (item["priority"], item["symbol"]))
            if row["symbol"].startswith("EQ")
        ]
        self.assertEqual(listing_priority("NYSE"), 80)
        self.assertEqual(listing_priority("NASDAQ"), 90)
        self.assertLess(
            repo.get_by_symbol("EQ000")["priority"],
            repo.get_by_symbol("EQ001")["priority"],
        )
        self.assertEqual(nyse_before_nasdaq[0], "EQ000")

    def test_repeated_discovery_is_idempotent(self) -> None:
        listings = [_listing("MSFT"), _listing("COST"), _listing("MSFT")]
        repo = UniverseExpansionRepository()
        first = ingest_us_equity_listings(repo, listings, discovery_capacity=8000)
        snapshot = {(row["symbol"], row["status"], row["priority"]) for row in repo.list_all()}
        second = ingest_us_equity_listings(repo, listings, discovery_capacity=8000)
        self.assertEqual(first.inserted, 2)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.skipped_existing, 2)
        self.assertEqual(
            {(row["symbol"], row["status"], row["priority"]) for row in repo.list_all()},
            snapshot,
        )

    def test_no_duplicate_identities_after_static_seed(self) -> None:
        repo = UniverseExpansionRepository()
        seed_universe_expansion_queue(repo)
        ingest_us_equity_listings(
            repo,
            [
                _listing("AAPL"),
                _listing("aapl"),
                _listing("BRK.B", exchange="NYSE"),
                _listing("JPM", sector="Financials"),
            ],
            discovery_capacity=8000,
        )
        symbols = [row["symbol"] for row in repo.list_all()]
        self.assertEqual(len(symbols), len(set(symbols)))
        self.assertEqual(symbols.count("AAPL"), 1)
        self.assertEqual(symbols.count("BRK-B"), 1)

    def test_excluded_instruments_are_not_queued(self) -> None:
        repo = UniverseExpansionRepository()
        report = ingest_us_equity_listings(
            repo,
            [
                _listing("AAPL-WT", name="Apple Warrant"),
                _listing("PREF^", name="Acme Preferred Stock"),
                _listing("NEWU-U", name="NewCo Units"),
                _listing("SPAC1", name="Special Purpose Acquisition Company"),
                _listing("LEV", name="ABC Inverse 2X Daily"),
                _listing("SPUS", name="SP Funds S&P 500 Sharia ETF", is_etf=True),
                _listing("MSFT", name="Microsoft Corporation"),
            ],
            discovery_capacity=8000,
        )
        queued = {row["symbol"] for row in repo.list_all()}
        self.assertEqual(queued, {"MSFT"})
        self.assertEqual(report.inserted, 1)
        self.assertGreaterEqual(report.skipped_excluded, 6)

    def test_listing_without_cik_is_not_queued(self) -> None:
        repo = UniverseExpansionRepository()
        report = ingest_us_equity_listings(
            repo,
            [_listing("NOCIK", cik=None)],
            discovery_capacity=8000,
        )
        self.assertEqual(report.inserted, 0)
        self.assertEqual(report.skipped_missing_cik, 1)
        self.assertEqual(repo.list_all(), [])

    def test_merged_nasdaq_sec_fixtures_dedupe_without_http(self) -> None:
        nasdaq = [
            {"symbol": "AAPL", "company_name": "Apple Inc", "exchange": "NASDAQ", "is_etf": False},
            {"symbol": "AAPL", "company_name": "Apple Inc dup", "exchange": "NASDAQ", "is_etf": False},
            {"symbol": "TQQQ", "company_name": "UltraPro QQQ", "exchange": "NASDAQ", "is_etf": True},
        ]
        other = [
            {"symbol": "JPM", "company_name": "JPMorgan", "exchange": "NYSE", "is_etf": False},
            {"symbol": "BRK.B", "company_name": "Berkshire", "exchange": "NYSE", "is_etf": False},
        ]
        sec = [
            {"symbol": "AAPL", "company_name": "Apple Inc", "cik": "320193"},
            {"symbol": "JPM", "company_name": "JPMorgan Chase", "cik": "19617"},
            {"symbol": "BRK-B", "company_name": "Berkshire Hathaway", "cik": "1067983"},
        ]
        merged = merge_exchange_and_sec_listings(nasdaq, other, sec)
        identities = [row["symbol"] for row in merged]
        self.assertEqual(len(identities), len(set(identities)))
        repo = UniverseExpansionRepository()
        ingest_us_equity_listings(repo, merged, discovery_capacity=8000)
        queued = {row["symbol"] for row in repo.list_all()}
        self.assertEqual(queued, {"AAPL", "JPM", "BRK-B"})
        self.assertNotIn("TQQQ", queued)


class QueueContractTests(unittest.TestCase):
    def test_pending_fairness_unchanged_on_large_queue(self) -> None:
        repo = UniverseExpansionRepository()
        retry = repo.upsert_pending("ORCL", source_universe="retry", priority=1)
        repo.finalize(
            retry["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                "next_retry_at": _now().isoformat(),
            },
        )
        ingest_us_equity_listings(
            repo,
            [_listing("ADP"), _listing("ZZZ", exchange="NYSE")],
            discovery_capacity=8000,
        )
        eligible = repo.list_eligible(_now(), limit=10)
        self.assertEqual(eligible[0]["status"], EXPANSION_STATUS_PENDING)
        self.assertEqual(eligible[-1]["symbol"], "ORCL")
        pending_symbols = [row["symbol"] for row in eligible if row["status"] == EXPANSION_STATUS_PENDING]
        self.assertEqual(pending_symbols, ["ZZZ", "ADP"])

    def test_uygun_degil_remains_terminal_and_ineligible(self) -> None:
        repo = UniverseExpansionRepository()
        rejected = repo.upsert_pending("JPM", source_universe="sp500", priority=1)
        repo.finalize(
            rejected["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_UYGUN_DEGIL,
                "next_retry_at": _now().isoformat(),
            },
        )
        ingest_us_equity_listings(repo, [_listing("JPM"), _listing("ADP")], discovery_capacity=8000)
        self.assertEqual(
            repo.get_by_symbol("JPM")["participation_status"],
            PARTICIPATION_STATUS_UYGUN_DEGIL,
        )
        eligible = [row["symbol"] for row in repo.list_eligible(_now(), limit=10)]
        self.assertNotIn("JPM", eligible)
        self.assertIn("ADP", eligible)

    def test_completed_excluded_from_eligibility_after_rediscovery(self) -> None:
        repo = UniverseExpansionRepository()
        done = repo.upsert_pending("MSFT", source_universe="pilot", priority=10)
        repo.finalize(
            done["id"],
            {
                "status": EXPANSION_STATUS_COMPLETED,
                "participation_status": PARTICIPATION_STATUS_UYGUN,
            },
        )
        ingest_us_equity_listings(repo, [_listing("MSFT")], discovery_capacity=8000)
        self.assertEqual(repo.get_by_symbol("MSFT")["status"], EXPANSION_STATUS_COMPLETED)
        eligible = [row["symbol"] for row in repo.list_eligible(_now(), limit=10)]
        self.assertNotIn("MSFT", eligible)

    def test_kontrol_et_remains_retryable(self) -> None:
        repo = UniverseExpansionRepository()
        row = repo.upsert_pending("ORCL", source_universe="retry", priority=1)
        repo.finalize(
            row["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                "next_retry_at": _now().isoformat(),
            },
        )
        ingest_us_equity_listings(repo, [_listing("ORCL")], discovery_capacity=8000)
        self.assertEqual(repo.get_by_symbol("ORCL")["status"], EXPANSION_STATUS_RETRYABLE)
        self.assertEqual(
            [item["symbol"] for item in repo.list_eligible(_now(), limit=10)],
            ["ORCL"],
        )

    def test_large_queue_does_not_change_per_run_safety_cap(self) -> None:
        repo = UniverseExpansionRepository()
        listings = [_listing(f"Q{index:03d}") for index in range(80)]
        ingest_us_equity_listings(
            repo,
            listings,
            discovery_capacity=8000,
            max_new_symbols_per_ingest=8000,
        )
        self.assertEqual(len(repo.list_all()), 80)
        config = UniverseExpansionBudgetConfig()
        self.assertEqual(config.max_symbols_per_run, 30)
        service = DailyUniverseExpansionService(
            queue_repo=repo,
            budget_config=config,
            onboarding_runner=lambda symbol, **kwargs: _ok(symbol),
        )
        report = service.run_once(max_symbols=config.max_symbols_per_run, now=_now(), seed_if_empty=False)
        self.assertEqual(report.stop_reason, STOP_REASON_SAFETY_CAP)
        self.assertEqual(report.symbols_started, 30)
        pending = [
            row for row in repo.list_all() if row["status"] == EXPANSION_STATUS_PENDING
        ]
        self.assertEqual(len(pending), 50)

    def test_discovery_capacity_does_not_raise_processing_cap(self) -> None:
        config = UniverseExpansionBudgetConfig(discovery_capacity=5000)
        self.assertEqual(config.max_symbols_per_run, 30)
        self.assertEqual(config.discovery_capacity, 5000)
        repo = UniverseExpansionRepository()
        listings = [_listing(f"C{index:03d}") for index in range(12)]
        report = ingest_us_equity_listings(repo, listings, discovery_capacity=5)
        self.assertEqual(report.inserted, 5)
        self.assertEqual(report.skipped_capacity, 7)
        self.assertEqual(len(repo.list_all()), 5)


class HalalFirewallTests(unittest.TestCase):
    def test_scanner_firewall_unchanged_for_scaled_universe(self) -> None:
        rows = [
            {"symbol": "CRM"},
            {"symbol": "AAPL"},
            {"symbol": "NVDA"},
            {"symbol": "NEWCO"},
            {"symbol": "SPUS"},
            {"symbol": "HOT"},
        ]
        eligible = filter_scanner_eligible_rows(
            rows,
            snapshots={
                "CRM": {"status": PARTICIPATION_STATUS_UYGUN},
                "AAPL": {"status": PARTICIPATION_STATUS_UYGUN_DEGIL},
            },
            candidates={
                "NVDA": {"participation_status": PARTICIPATION_STATUS_KONTROL_ET},
                "HOT": {"nabi_score": 99, "decision": "GÜÇLÜ ADAY"},
            },
            catalog_defaults={"SPUS": (PARTICIPATION_STATUS_UYGUN, 100)},
        )
        self.assertEqual([row["symbol"] for row in eligible], ["CRM", "SPUS"])

    def test_nabi_score_cannot_bypass_missing_participation(self) -> None:
        eligible = filter_scanner_eligible_rows(
            [{"symbol": "HOT"}],
            candidates={"HOT": {"nabi_score": 99, "decision": "ADAY"}},
        )
        self.assertEqual(eligible, [])


class ExternalSignalHookTests(unittest.TestCase):
    def test_external_signal_cannot_bypass_participation(self) -> None:
        repo = UniverseExpansionRepository()
        report = propose_symbols_from_external_signal(
            ["TSLA", "tsla", "AAPL-WT", "MSFT"],
            repo=repo,
            discovery_capacity=8000,
        )
        self.assertEqual(report.inserted, 2)
        tsla = repo.get_by_symbol("TSLA")
        self.assertEqual(tsla["status"], EXPANSION_STATUS_PENDING)
        self.assertFalse(tsla.get("participation_status"))
        self.assertNotEqual(tsla.get("participation_status"), PARTICIPATION_STATUS_UYGUN)
        self.assertIsNone(repo.get_by_symbol("AAPL-WT"))
        eligible = filter_scanner_eligible_rows(
            [{"symbol": "TSLA"}, {"symbol": "MSFT"}],
            candidates={row["symbol"]: row for row in repo.list_all()},
        )
        self.assertEqual(eligible, [])
        for row in repo.list_all():
            fake_aday = {
                **row,
                "nabi_score": 95,
                "decision": "GÜÇLÜ ADAY",
                "current_price": 10,
            }
            self.assertFalse(is_actionable_opportunity(fake_aday))
        mock_scanner = MagicMock()
        propose_symbols_from_external_signal(["NVDA"], repo=repo, discovery_capacity=8000)
        mock_scanner.assert_not_called()


class MetricsTests(unittest.TestCase):
    def test_compact_discovery_metrics(self) -> None:
        repo = UniverseExpansionRepository()
        pending = repo.upsert_pending("AAA", source_universe="pilot", priority=1)
        retry = repo.upsert_pending("BBB", source_universe="pilot", priority=2)
        done = repo.upsert_pending("CCC", source_universe="pilot", priority=3)
        rejected = repo.upsert_pending("DDD", source_universe="pilot", priority=4)
        kontrol = repo.upsert_pending("EEE", source_universe="pilot", priority=5)
        repo.finalize(pending["id"], {"status": EXPANSION_STATUS_PENDING})
        repo.finalize(
            retry["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
            },
        )
        repo.finalize(
            done["id"],
            {
                "status": EXPANSION_STATUS_COMPLETED,
                "participation_status": PARTICIPATION_STATUS_UYGUN,
            },
        )
        repo.finalize(
            rejected["id"],
            {
                "status": EXPANSION_STATUS_COMPLETED,
                "participation_status": PARTICIPATION_STATUS_UYGUN_DEGIL,
            },
        )
        repo.finalize(
            kontrol["id"],
            {
                "status": EXPANSION_STATUS_RETRYABLE,
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
            },
        )
        metrics = collect_universe_discovery_metrics(repo)
        self.assertEqual(metrics.known_universe_size, 5)
        self.assertEqual(metrics.pending_participation, 1)
        self.assertEqual(metrics.retryable, 2)
        self.assertEqual(metrics.completed, 2)
        self.assertEqual(metrics.uygun, 1)
        self.assertEqual(metrics.uygun_degil, 1)
        self.assertEqual(metrics.kontrol_et, 2)


if __name__ == "__main__":
    unittest.main()
