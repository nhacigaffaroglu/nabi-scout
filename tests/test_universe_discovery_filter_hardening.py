from __future__ import annotations

import unittest

from config.universe_expansion_config import UniverseExpansionBudgetConfig
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.free_universe_client import FreeUniverseClient
from services.universe_discovery_listings import (
    merge_exchange_and_sec_listings,
    select_us_equity_discovery_candidates,
)
from services.universe_discovery_service import ingest_us_equity_listings
from services.universe_listing_identity import (
    excluded_instrument_reason,
    excluded_security_name,
    instrument_name_exclusion_reason,
    is_ordinary_equity_listing,
    listing_identity,
)


def _listing(
    symbol: str,
    *,
    name: str | None = None,
    exchange: str = "NASDAQ",
    cik: str | None = "100",
    is_etf: bool = False,
    exchange_security_name: str | None = None,
) -> dict:
    payload = {
        "symbol": symbol,
        "company_name": name or symbol,
        "exchange": exchange,
        "cik": cik,
        "is_etf": is_etf,
    }
    if exchange_security_name is not None:
        payload["exchange_security_name"] = exchange_security_name
    return payload


class FooterParseTests(unittest.TestCase):
    def test_file_creation_time_variants_are_ignored(self) -> None:
        client = FreeUniverseClient(contact_email="test@example.com")
        for raw in (
            "File Creation Time: 0827202614:02",
            "FILE CREATION TIME: 0827202614:02",
            "file creation time: 0827202614:02",
        ):
            self.assertTrue(client.is_file_creation_time_symbol(raw), msg=raw)
        self.assertFalse(client.is_file_creation_time_symbol("AAPL"))
        self.assertFalse(client.is_file_creation_time_symbol("FILE"))

    def test_nasdaq_listed_parser_drops_uppercase_footer(self) -> None:
        client = FreeUniverseClient(contact_email="test@example.com")
        client._download_text = lambda url: (  # type: ignore[method-assign]
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
            "Round Lot Size|ETF|NextShares\n"
            "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
            "FILE CREATION TIME: 0827202614:02|||||||\n"
        )
        rows = client.get_nasdaq_listed()
        self.assertEqual([row["symbol"] for row in rows], ["AAPL"])


class OrdinaryNameFalsePositiveTests(unittest.TestCase):
    def test_ordinary_commons_survive_unit_spac_right_substrings(self) -> None:
        cases = (
            ("UNH", "UnitedHealth Group Incorporated Common Stock"),
            ("UPS", "United Parcel Service, Inc. Common Stock"),
            ("UAL", "United Airlines Holdings Inc"),
            ("GE", "GE Aerospace Common Stock"),
            ("EXR", "Extra Space Storage Inc Common Stock"),
            ("BFAM", "Bright Horizons Family Solutions Inc Common Stock"),
            ("WMGI", "Wright Medical Group N.V. Common Stock"),
            ("CW", "Curtiss-Wright Corporation Common Stock"),
            ("TXG", "10x Genomics Inc Common Stock"),
        )
        for symbol, name in cases:
            self.assertIsNone(
                excluded_instrument_reason(symbol=symbol, company_name=name),
                msg=name,
            )
            self.assertFalse(excluded_security_name(name), msg=name)
            self.assertTrue(
                is_ordinary_equity_listing(_listing(symbol, name=name)),
                msg=name,
            )


class NonCommonExclusionTests(unittest.TestCase):
    def test_actual_instrument_names_are_excluded(self) -> None:
        cases = (
            ("EXU", "Example Units", "excluded_name"),
            ("EXU2", "Example Unit", "excluded_name"),
            ("EXW", "Example Warrant", "excluded_name"),
            ("EXW2", "Example Warrants", "excluded_name"),
            ("EXRGT", "Example Right", "excluded_name"),
            ("EXRGT2", "Example Rights", "excluded_name"),
            ("EXP", "Example Preferred Stock", "preferred"),
            ("LILAP", "Example Preference Shares", "preferred"),
            ("SPX", "Example SPAC", "excluded_name"),
            ("ACQ", "Example Acquisition Corp", "excluded_name"),
            ("ETN1", "Example ETN", "etn"),
            ("ETN2", "Example Exchange-Traded Notes", "etn"),
            ("CEF1", "Example Closed-End Fund", "closed_end_fund"),
            ("NTE1", "Example Senior Notes due 2030", "listed_note"),
            ("NTE2", "Example Subordinated Notes due 2035", "listed_note"),
        )
        for symbol, name, expected in cases:
            self.assertEqual(
                excluded_instrument_reason(symbol=symbol, company_name=name),
                expected,
                msg=name,
            )
            self.assertFalse(is_ordinary_equity_listing(_listing(symbol, name=name)))

    def test_etn_word_boundary_does_not_match_random_letters(self) -> None:
        self.assertIsNone(
            instrument_name_exclusion_reason("Marketnet Holdings Common Stock")
        )
        self.assertEqual(
            instrument_name_exclusion_reason(
                "iPath Series B S&P 500 VIX Short-Term Futures ETN"
            ),
            "etn",
        )

    def test_dry_run_etn_exchange_names_are_excluded(self) -> None:
        names = (
            "ETRACS Alerian MLP Index ETN Series B due July 18, 2042",
            "iPath Select MLP ETN",
            "ETRACS MarketVector Business Development Companies Liquid Index ETN due April 26, 2041",
            "DB Gold Double Long ETN due February 15, 2038",
            "iPath Bloomberg Commodity Index Total Return ETN",
            "iPath Series B Carbon Exchange-Traded Notes",
            "iPath Series B S&P 500 VIX Short-Term Futures ETN",
        )
        for name in names:
            self.assertEqual(instrument_name_exclusion_reason(name), "etn", msg=name)


class ExchangeNameEvidenceTests(unittest.TestCase):
    def test_sec_issuer_name_cannot_overwrite_exchange_etn_evidence(self) -> None:
        nasdaq = [
            {
                "symbol": "FNGD",
                "company_name": (
                    "MicroSectors FANG Index -3X Inverse Leveraged ETNs "
                    "due January 8, 2038"
                ),
                "exchange": "NYSE Arca",
                "is_etf": False,
            },
            {
                "symbol": "FNGO",
                "company_name": (
                    "MicroSectors FANG Index 2X Leveraged ETNs due January 8, 2038"
                ),
                "exchange": "NYSE Arca",
                "is_etf": False,
            },
            {
                "symbol": "SMHB",
                "company_name": (
                    "ETRACS Monthly Pay 2x Leveraged Small Cap High Dividend ETN Series B"
                ),
                "exchange": "NYSE Arca",
                "is_etf": False,
            },
        ]
        sec = [
            {"symbol": "FNGD", "company_name": "BANK OF MONTREAL /CAN/", "cik": "927971"},
            {"symbol": "FNGO", "company_name": "BANK OF MONTREAL /CAN/", "cik": "927971"},
            {"symbol": "SMHB", "company_name": "UBS AG", "cik": "1114446"},
        ]
        merged = merge_exchange_and_sec_listings(nasdaq, [], sec)
        by_symbol = {row["symbol"]: row for row in merged}
        self.assertEqual(by_symbol["FNGD"]["company_name"], "BANK OF MONTREAL /CAN/")
        self.assertIn("ETNs", by_symbol["FNGD"]["exchange_security_name"])
        selected = {row.symbol for row in select_us_equity_discovery_candidates(merged)}
        self.assertEqual(selected, set())
        for symbol in ("FNGD", "FNGO", "SMHB"):
            self.assertFalse(is_ordinary_equity_listing(by_symbol[symbol]))

    def test_preference_and_notes_use_exchange_security_name(self) -> None:
        rows = [
            _listing(
                "LILAP",
                name="LIBERTY LATIN AMERICA LTD",
                exchange_security_name=(
                    "Liberty Latin America Ltd. - 9.0% Fixed Rate Cumulative "
                    "Perpetual Redeemable Series A Preference Shares"
                ),
            ),
            _listing(
                "AQNB",
                name="ALGONQUIN POWER & UTILITIES CORP.",
                exchange="NYSE",
                exchange_security_name=(
                    "Algonquin Power & Utilities Corp. 6.20% Fixed-to-Floating "
                    "Subordinated Notes Series 2019-A due July 1, 2079"
                ),
            ),
        ]
        selected = select_us_equity_discovery_candidates(rows)
        self.assertEqual(selected, [])
        self.assertEqual(
            excluded_instrument_reason(
                symbol="LILAP",
                company_name="LIBERTY LATIN AMERICA LTD",
                exchange_security_name=rows[0]["exchange_security_name"],
            ),
            "preferred",
        )
        self.assertEqual(
            excluded_instrument_reason(
                symbol="AQNB",
                company_name="ALGONQUIN POWER & UTILITIES CORP.",
                exchange_security_name=rows[1]["exchange_security_name"],
            ),
            "listed_note",
        )

    def test_closed_end_fund_requires_explicit_exchange_evidence(self) -> None:
        self.assertEqual(
            excluded_instrument_reason(
                symbol="ACP",
                company_name="abrdn Income Credit Strategies Fund",
                exchange_security_name="abrdn Income Credit Strategies Fund Closed End Fund",
            ),
            "closed_end_fund",
        )
        self.assertIsNone(
            excluded_instrument_reason(
                symbol="MSFT",
                company_name="Microsoft Corporation",
                exchange_security_name="Microsoft Corporation - Common Stock",
            )
        )


class IngestBatchLimitTests(unittest.TestCase):
    def test_default_ingest_limit_is_thirty_and_independent_of_capacity(self) -> None:
        config = UniverseExpansionBudgetConfig()
        self.assertEqual(config.max_new_symbols_per_ingest, 30)
        self.assertEqual(config.discovery_capacity, 8000)
        self.assertEqual(config.max_symbols_per_run, 30)

    def test_ingest_inserts_at_most_thirty_new_identities(self) -> None:
        listings = [
            _listing(f"NY{index:03d}", exchange="NYSE")
            for index in range(80)
        ]
        repo = UniverseExpansionRepository()
        report = ingest_us_equity_listings(repo, listings, discovery_capacity=8000)
        queued = [row["symbol"] for row in repo.list_all()]
        self.assertEqual(report.inserted, 30)
        self.assertEqual(len(queued), 30)
        self.assertEqual(queued, [f"NY{index:03d}" for index in range(30)])
        self.assertEqual(report.skipped_ingest_limit, 50)
        self.assertEqual(report.skipped_capacity, 0)

    def test_second_ingest_progresses_to_next_thirty_without_duplicates(self) -> None:
        listings = [
            _listing(f"NY{index:03d}", exchange="NYSE")
            for index in range(80)
        ]
        repo = UniverseExpansionRepository()
        first = ingest_us_equity_listings(repo, listings, discovery_capacity=8000)
        second = ingest_us_equity_listings(repo, listings, discovery_capacity=8000)
        queued = [row["symbol"] for row in sorted(repo.list_all(), key=lambda item: item["symbol"])]
        self.assertEqual(first.inserted, 30)
        self.assertEqual(second.inserted, 30)
        self.assertEqual(second.skipped_existing, 30)
        self.assertEqual(len(queued), 60)
        self.assertEqual(len(set(queued)), 60)
        first_batch = [f"NY{index:03d}" for index in range(30)]
        second_batch = [f"NY{index:03d}" for index in range(30, 60)]
        self.assertEqual(
            [row["symbol"] for row in sorted(repo.list_all(), key=lambda item: (item["priority"], item["symbol"]))][:30],
            first_batch,
        )
        self.assertEqual(set(queued) & set(first_batch), set(first_batch))
        self.assertEqual(set(queued) & set(second_batch), set(second_batch))

    def test_capacity_still_caps_below_ingest_limit(self) -> None:
        listings = [_listing(f"AA{index:02d}", exchange="NYSE") for index in range(40)]
        repo = UniverseExpansionRepository()
        report = ingest_us_equity_listings(
            repo,
            listings,
            discovery_capacity=10,
            max_new_symbols_per_ingest=30,
        )
        self.assertEqual(report.inserted, 10)
        self.assertEqual(report.skipped_capacity, 30)
        self.assertEqual(report.skipped_ingest_limit, 0)

    def test_zero_ingest_limit_inserts_nothing(self) -> None:
        repo = UniverseExpansionRepository()
        report = ingest_us_equity_listings(
            repo,
            [_listing("MSFT"), _listing("AAPL")],
            discovery_capacity=8000,
            max_new_symbols_per_ingest=0,
        )
        self.assertEqual(report.inserted, 0)
        self.assertEqual(report.skipped_ingest_limit, 2)
        self.assertEqual(repo.list_all(), [])

    def test_negative_ingest_limit_is_treated_as_zero(self) -> None:
        repo = UniverseExpansionRepository()
        report = ingest_us_equity_listings(
            repo,
            [_listing("MSFT")],
            max_new_symbols_per_ingest=-5,
        )
        self.assertEqual(report.inserted, 0)
        self.assertEqual(report.skipped_ingest_limit, 1)

    def test_existing_queue_identities_are_skipped_before_limit(self) -> None:
        repo = UniverseExpansionRepository()
        repo.upsert_pending("AAPL", source_universe="pilot_equity", priority=10)
        listings = [_listing("AAPL"), _listing("MSFT"), _listing("COST")]
        report = ingest_us_equity_listings(
            repo,
            listings,
            discovery_capacity=8000,
            max_new_symbols_per_ingest=1,
        )
        self.assertEqual(report.skipped_existing, 1)
        self.assertEqual(report.inserted, 1)
        self.assertEqual(report.skipped_ingest_limit, 1)
        self.assertEqual(
            {row["symbol"] for row in repo.list_all()},
            {"AAPL", "COST"},
        )

    def test_brk_identity_normalization_unchanged(self) -> None:
        self.assertEqual(listing_identity("BRK.B"), "BRK-B")
        repo = UniverseExpansionRepository()
        ingest_us_equity_listings(
            repo,
            [
                _listing("BRK.B", name="Berkshire Hathaway", exchange="NYSE"),
                _listing("BRK-B", name="Berkshire Hathaway", exchange="NYSE"),
            ],
            discovery_capacity=8000,
        )
        symbols = [row["symbol"] for row in repo.list_all()]
        self.assertEqual(symbols, ["BRK-B"])


if __name__ == "__main__":
    unittest.main()
