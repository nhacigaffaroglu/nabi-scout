from __future__ import annotations

import unittest
from pathlib import Path

from services.fund_intelligence_contract import FundHoldingRow
from services.portfolio_economic_exposure import (
    _HOLDING_ASSET_TYPE_MAP,
    classify_instrument_exposure,
)
from services.security_master_contract import (
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_CASH,
    INSTRUMENT_EQUITY,
    INSTRUMENT_ETF,
    INSTRUMENT_REIT,
    INSTRUMENT_SUKUK,
    INSTRUMENT_UNKNOWN,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
    SOURCE_CANONICAL_STATIC,
    SOURCE_US_LISTING,
    SecurityFact,
)
from services.security_master_service import (
    SecurityMasterService,
    infer_identifier_type,
    summarize_holding_coverage,
)
from tests.test_portfolio_economic_exposure import _etf, _snapshot


ENGINE = Path("services/portfolio_economic_exposure.py")
SM_SERVICE = Path("services/security_master_service.py")
MIGRATION = Path("database/migration_security_master.sql")


def _listing(
    symbol: str,
    *,
    cik: str = "100",
    is_etf: bool = False,
    name: str | None = None,
    exchange: str = "NASDAQ",
) -> dict:
    return {
        "symbol": symbol,
        "company_name": name or f"{symbol} Corporation",
        "exchange": exchange,
        "cik": cik,
        "is_etf": is_etf,
    }


class IdentifierAndFactTests(unittest.TestCase):
    def test_proven_us_ordinary_equity(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("MSFT", cik="789019")])
        resolution = master.resolve_security("MSFT")
        self.assertEqual(resolution.status, RESOLUTION_RESOLVED)
        self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(resolution.source, SOURCE_US_LISTING)

    def test_etf_listing_is_not_equity(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts(
            [_listing("QQQ", cik="106783", is_etf=True, name="Invesco QQQ Trust ETF")]
        )
        resolution = master.resolve_security("QQQ")
        self.assertEqual(resolution.instrument_type, INSTRUMENT_ETF)
        self.assertNotEqual(resolution.instrument_type, INSTRUMENT_EQUITY)

    def test_unknown_identifier_unresolved(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        resolution = master.resolve_security("NOTREAL")
        self.assertEqual(resolution.status, RESOLUTION_UNKNOWN)
        self.assertEqual(resolution.instrument_type, INSTRUMENT_UNKNOWN)

    def test_missing_evidence_does_not_default_to_equity(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("MSFT", cik="789019")])
        resolution = master.resolve_security("ZZZZQ")
        self.assertNotEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(resolution.instrument_type, INSTRUMENT_UNKNOWN)

    def test_name_containing_reit_does_not_prove_reit(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        resolution = master.resolve_security("O")
        self.assertNotEqual(resolution.instrument_type, INSTRUMENT_REIT)
        listing_master = SecurityMasterService(include_canonical_static=False)
        listing_master.ingest_listing_facts(
            [_listing("O", cik="726728", name="Realty Income REIT", exchange="NYSE")]
        )
        listed = listing_master.resolve_security("O")
        self.assertEqual(listed.instrument_type, INSTRUMENT_EQUITY)
        self.assertNotEqual(listed.instrument_type, INSTRUMENT_REIT)

    def test_name_containing_sukuk_does_not_prove_sukuk(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        fact = master.resolve_security("BOND1")
        self.assertNotEqual(fact.instrument_type, INSTRUMENT_SUKUK)
        self.assertEqual(fact.instrument_type, INSTRUMENT_UNKNOWN)

    def test_international_ticker_without_evidence_unknown(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("AAPL", cik="320193")])
        resolution = master.resolve_security("7203")
        self.assertEqual(resolution.instrument_type, INSTRUMENT_UNKNOWN)

    def test_cusip_and_sedol_without_evidence_unknown(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        cusip = master.resolve_security("037833100")
        sedol = master.resolve_security("B1YWRK7")
        self.assertEqual(infer_identifier_type("037833100"), IDENTIFIER_TYPE_CUSIP)
        self.assertEqual(infer_identifier_type("B1YWRK7"), IDENTIFIER_TYPE_SEDOL)
        self.assertEqual(cusip.identifier_type, IDENTIFIER_TYPE_CUSIP)
        self.assertEqual(sedol.identifier_type, IDENTIFIER_TYPE_SEDOL)
        self.assertEqual(cusip.instrument_type, INSTRUMENT_UNKNOWN)
        self.assertEqual(sedol.instrument_type, INSTRUMENT_UNKNOWN)

    def test_conflict_fail_closed(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(
            SecurityFact("MSFT", IDENTIFIER_TYPE_TICKER, INSTRUMENT_EQUITY, "alpha", "2026-01-01T00:00:00+00:00")
        )
        master.upsert_security_fact(
            SecurityFact("MSFT", IDENTIFIER_TYPE_TICKER, INSTRUMENT_ETF, "beta", "2026-08-01T00:00:00+00:00")
        )
        resolution = master.resolve_security("MSFT")
        self.assertEqual(resolution.status, RESOLUTION_CONFLICT)
        self.assertEqual(resolution.instrument_type, INSTRUMENT_UNKNOWN)
        self.assertEqual(resolution.limitation, "SOURCE_CONFLICT")

    def test_source_provenance_preserved(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("MSFT", cik="789019")])
        resolution = master.resolve_security("MSFT")
        self.assertEqual(resolution.source, SOURCE_US_LISTING)
        self.assertEqual(resolution.facts[0].source, SOURCE_US_LISTING)
        self.assertEqual(resolution.facts[0].metadata.get("cik"), "789019")

    def test_upsert_idempotent(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        fact = SecurityFact(
            "MSFT",
            IDENTIFIER_TYPE_TICKER,
            INSTRUMENT_EQUITY,
            SOURCE_US_LISTING,
            "2026-08-27T00:00:00+00:00",
            metadata={"cik": "789019"},
        )
        first = master.upsert_security_fact(fact)
        second = master.upsert_security_fact(fact)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(master.get_security_facts("MSFT")), 1)


class LookthroughIntegrationTests(unittest.TestCase):
    def test_lookthrough_consumes_security_master_fact(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("MSFT", cik="789019")])
        snapshot = _snapshot(
            "FUNDX",
            (FundHoldingRow("MSFT", "Microsoft", 100.0, None, None, None),),
        )
        view = classify_instrument_exposure(
            _etf("FUNDX"),
            fund_snapshots={"FUNDX": snapshot},
            security_master=master,
        )
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "equity")
        self.assertAlmostEqual(view.economic_exposures[0].weight_pct, 100.0)

    def test_lookthrough_unknown_remains_unknown(self) -> None:
        snapshot = _snapshot(
            "FUNDY",
            (FundHoldingRow("ZZZZQ", "Mystery Co", 100.0, None, None, None),),
        )
        view = classify_instrument_exposure(_etf("FUNDY"), fund_snapshots={"FUNDY": snapshot})
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "unknown")

    def test_spsk_identity_does_not_classify_constituents_as_sukuk(self) -> None:
        snapshot = _snapshot(
            "SPSK",
            (FundHoldingRow("B1YWRK7", "SP Funds Sukuk Holding", 100.0, None, None, None),),
        )
        view = classify_instrument_exposure(_etf("SPSK"), fund_snapshots={"SPSK": snapshot})
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "unknown")
        self.assertNotEqual(view.economic_exposures[0].exposure_bucket, "sukuk")

    def test_spre_identity_does_not_classify_constituents_as_reit(self) -> None:
        snapshot = _snapshot(
            "SPRE",
            (FundHoldingRow("O", "Realty Income REIT", 80.0, None, None, None),),
            coverage=80.0,
        )
        view = classify_instrument_exposure(_etf("SPRE"), fund_snapshots={"SPRE": snapshot})
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertNotIn("real_estate", buckets)

    def test_issuer_weight_rounding_preserves_raw_and_scales_aggregate(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.ingest_listing_facts([_listing("MSFT", cik="1"), _listing("NVDA", cik="2")])
        snapshot = _snapshot(
            "OVER",
            (
                FundHoldingRow("MSFT", "Microsoft", 50.07, None, None, None),
                FundHoldingRow("NVDA", "NVIDIA", 50.07, None, None, None),
            ),
        )
        self.assertAlmostEqual(sum(row.weight_pct or 0 for row in snapshot.holdings), 100.14)
        view = classify_instrument_exposure(
            _etf("OVER"),
            fund_snapshots={"OVER": snapshot},
            security_master=master,
        )
        self.assertEqual(len(view.economic_exposures), 1)
        self.assertAlmostEqual(view.economic_exposures[0].weight_pct, 100.0)
        self.assertIn("ISSUER_WEIGHT_ROUNDING_NORMALIZED", view.economic_exposures[0].limitations)
        self.assertAlmostEqual(snapshot.holdings[0].weight_pct, 50.07)

    def test_economic_exposure_mapping_unchanged(self) -> None:
        self.assertEqual(
            _HOLDING_ASSET_TYPE_MAP,
            {
                "equity": "equity",
                "stock": "equity",
                "common stock": "equity",
                "sukuk": "sukuk",
                "fixed_income": "fixed_income",
                "fixed income": "fixed_income",
                "bond": "fixed_income",
                "reit": "real_estate",
                "real_estate": "real_estate",
                "real estate": "real_estate",
                "cash": "cash",
                "cash_equivalent": "cash",
                "commodity": "commodity",
                "gold": "commodity",
            },
        )

    def test_participation_and_new_money_do_not_import_security_master(self) -> None:
        participation = Path("services/universe_expansion_onboarding_service.py").read_text(encoding="utf-8")
        new_money = Path("services/wealth_new_money_allocation.py").read_text(encoding="utf-8")
        self.assertNotIn("security_master", participation)
        self.assertNotIn("security_master", new_money)

    def test_cash_identifier_is_cash_not_name_guess(self) -> None:
        master = SecurityMasterService()
        self.assertEqual(master.resolve_security("CASH").instrument_type, INSTRUMENT_CASH)
        self.assertEqual(master.resolve_security("Cash&Other").instrument_type, INSTRUMENT_UNKNOWN)

    def test_canonical_allowlist_still_resolves_without_listing(self) -> None:
        master = SecurityMasterService()
        resolution = master.resolve_security("AAPL")
        self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(resolution.source, SOURCE_CANONICAL_STATIC)


class CoverageReplayTests(unittest.TestCase):
    def test_sp_funds_style_coverage_before_after_listing_index(self) -> None:
        spus = (
            FundHoldingRow("AAPL", "Apple", 20.13, None, None, None),
            FundHoldingRow("MSFT", "Microsoft", 59.87, None, None, None),
            FundHoldingRow("CASH", "Cash&Other", 0.14, None, None, None),
            FundHoldingRow("7203", "Toyota", 20.00, None, None, None),
        )
        spsk = (
            FundHoldingRow("B1YWRK7", "SP Funds Sukuk Holding", 60.0, None, None, None),
            FundHoldingRow("037833100", "Named Sukuk Note", 40.0, None, None, None),
        )
        spre = (FundHoldingRow("O", "Realty Income REIT", 100.0, None, None, None),)
        spwo = (FundHoldingRow("7203", "Toyota Motor", 100.0, None, None, None),)

        before = SecurityMasterService()
        after = SecurityMasterService()
        after.ingest_listing_facts(
            [
                _listing("AAPL", cik="320193"),
                _listing("MSFT", cik="789019"),
                _listing("O", cik="726728", name="Realty Income Corporation", exchange="NYSE"),
            ]
        )

        spus_before = summarize_holding_coverage(spus, security_master=before)
        spus_after = summarize_holding_coverage(spus, security_master=after)
        self.assertGreater(spus_before["classified_EQUITY"], 0)
        self.assertGreater(spus_after["classified_EQUITY"], spus_before["classified_EQUITY"])
        self.assertGreater(spus_after["classified_CASH"], 0)
        self.assertGreater(spus_after["UNKNOWN"], 0)

        spsk_before = summarize_holding_coverage(spsk, security_master=before)
        spsk_after = summarize_holding_coverage(spsk, security_master=after)
        self.assertEqual(spsk_before["classified_SUKUK"], 0)
        self.assertEqual(spsk_after["classified_SUKUK"], 0)
        self.assertAlmostEqual(spsk_after["UNKNOWN"], 100.0)

        spre_before = summarize_holding_coverage(spre, security_master=before)
        spre_after = summarize_holding_coverage(spre, security_master=after)
        self.assertEqual(spre_before["classified_REIT"], 0)
        self.assertEqual(spre_after["classified_REIT"], 0)

        spwo_after = summarize_holding_coverage(spwo, security_master=after)
        self.assertAlmostEqual(spwo_after["UNKNOWN"], 100.0)

    def test_no_llm_or_fund_identity_inference(self) -> None:
        source = SM_SERVICE.read_text(encoding="utf-8")
        self.assertNotIn("openai", source.lower())
        self.assertNotIn('if symbol == "SPSK"', source)
        self.assertNotIn("therefore sukuk", source.lower())
        engine = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("KNOWN_EQUITY_US", engine)

    def test_migration_contract(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("security_master", sql)
        self.assertIn("PRE-DEPLOY MIGRATION REQUIRED", sql)
        self.assertIn("identifier_type", sql)
        self.assertIn("instrument_type", sql)
        self.assertIn("unique (identifier, identifier_type, source)", sql)


if __name__ == "__main__":
    unittest.main()
