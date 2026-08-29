from __future__ import annotations

import unittest
from pathlib import Path

from services.fund_intelligence_contract import FundHoldingRow, FundHoldingsSnapshotView
from services.openfigi_client import (
    ID_SEDOL,
    MATCH_EXACT_SINGLE,
    OpenFigiCandidate,
    OpenFigiJob,
    OpenFigiJobResult,
)
from services.openfigi_evidence_qualification import qualify_mapping
from services.openfigi_security_master_ingest import (
    ACTION_SKIP,
    canonical_openfigi_instrument,
    fact_from_qualification,
    plan_openfigi_ingest,
)
from services.portfolio_economic_exposure import classify_instrument_exposure
from services.portfolio_intelligence_contract import PositionValuationRow
from services.reit_evidence_contract import (
    REIT_MODEL_GAP,
    classify_from_name_or_fund,
    is_explicit_structured_reit,
    listing_equity_is_not_reit,
    may_persist_reit_fact,
    name_is_not_evidence,
    persist_blocked_reason,
    spre_membership_is_not_evidence,
)
from services.security_master_contract import (
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_EQUITY,
    INSTRUMENT_REIT,
    INSTRUMENT_UNKNOWN,
    SOURCE_PROVIDER_EXPLICIT,
    SOURCE_US_LISTING,
    SecurityFact,
)
from services.security_master_service import SecurityMasterService


def _etf(symbol: str) -> PositionValuationRow:
    return PositionValuationRow(
        position_id=f"x-{symbol}",
        account_id="",
        asset_id="",
        symbol=symbol,
        asset_class="etf",
        account_name="",
        quantity=1,
        average_cost=1,
        valuation_currency="USD",
        price=1,
        price_available=True,
        market_value=1,
        cost_basis=1,
        unrealized_pl=0,
        weight_pct=1,
        is_cash=False,
        included_in_base_totals=True,
    )


def _snapshot(symbol: str, holdings) -> FundHoldingsSnapshotView:
    return FundHoldingsSnapshotView(
        fund_symbol=symbol,
        fund_type="etf",
        as_of="2026-08-28",
        source="sp_funds_official",
        coverage_pct=100.0,
        underlying_count=len(holdings),
        holdings=tuple(holdings),
        data_quality="good",
        limitation="",
    )


class ReitContractTests(unittest.TestCase):
    def test_name_and_spre_are_not_evidence(self) -> None:
        self.assertTrue(name_is_not_evidence("IGB Real Estate Investment Trust"))
        self.assertTrue(spre_membership_is_not_evidence("SPRE"))
        self.assertEqual(classify_from_name_or_fund("Realty Income REIT", "SPRE"), INSTRUMENT_UNKNOWN)

    def test_structured_reit_token_is_explicit_but_not_persisted(self) -> None:
        self.assertTrue(is_explicit_structured_reit("REIT", "REIT"))
        self.assertFalse(is_explicit_structured_reit("COMMON STOCK"))
        self.assertTrue(REIT_MODEL_GAP)
        self.assertFalse(may_persist_reit_fact())
        self.assertIn("instrument_type cannot hold both", persist_blocked_reason())

    def test_listing_equity_is_not_silently_reit(self) -> None:
        self.assertTrue(listing_equity_is_not_reit(INSTRUMENT_EQUITY, source=SOURCE_US_LISTING))
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(
            SecurityFact(
                "WELL",
                IDENTIFIER_TYPE_TICKER,
                INSTRUMENT_EQUITY,
                SOURCE_US_LISTING,
                "2026-08-28T00:00:00+00:00",
            )
        )
        master.upsert_security_fact(
            SecurityFact(
                "WELL",
                IDENTIFIER_TYPE_TICKER,
                INSTRUMENT_REIT,
                SOURCE_PROVIDER_EXPLICIT,
                "2026-08-28T00:00:00+00:00",
            )
        )
        resolved = master.resolve_security("WELL")
        self.assertEqual(resolved.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(resolved.source, SOURCE_US_LISTING)
        self.assertNotEqual(resolved.instrument_type, INSTRUMENT_REIT)

    def test_sedol_reit_fact_does_not_classify_ticker_lookthrough(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(
            SecurityFact(
                "B89JCF2",
                IDENTIFIER_TYPE_SEDOL,
                INSTRUMENT_REIT,
                SOURCE_PROVIDER_EXPLICIT,
                "2026-08-28T00:00:00+00:00",
            )
        )
        snapshot = _snapshot(
            "SPRE",
            (FundHoldingRow("IGBREIT MK", "IGB Real Estate Investment Trust", 100.0, None, None, None),),
        )
        view = classify_instrument_exposure(
            _etf("SPRE"),
            fund_snapshots={"SPRE": snapshot},
            security_master=master,
        )
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertNotIn("real_estate", buckets)
        self.assertIn("unknown", buckets)

    def test_openfigi_reit_is_not_ingested(self) -> None:
        job = OpenFigiJob(ID_SEDOL, "B89JCF2")
        candidate = OpenFigiCandidate(
            figi="BBG0038P24J8",
            name="IGB REAL ESTATE INV TRUST",
            ticker="IGBREIT",
            exch_code="MK",
            security_type="REIT",
            security_type2="REIT",
            market_sector="Equity",
            composite_figi="",
            share_class_figi="",
        )
        result = OpenFigiJobResult(
            job=job,
            match_status=MATCH_EXACT_SINGLE,
            http_status=200,
            candidates=(candidate,),
        )
        qualification = qualify_mapping(result)
        self.assertEqual(qualification.instrument_type, INSTRUMENT_REIT)
        self.assertEqual(canonical_openfigi_instrument(qualification), "")
        self.assertIsNone(fact_from_qualification(job, qualification))
        plan = plan_openfigi_ingest(((job, result, 4.01),))
        self.assertEqual(plan.inserts, 0)
        self.assertEqual(plan.rows[0].action, ACTION_SKIP)
        self.assertEqual(plan.sukuk_planned, 0)


class SourceLockTests(unittest.TestCase):
    def test_ingest_never_writes_reit(self) -> None:
        text = Path("services/openfigi_security_master_ingest.py").read_text(encoding="utf-8")
        self.assertIn("Never writes SUKUK", text)
        self.assertIn("Persists identity + FIXED_INCOME facts only", text)
        self.assertNotIn("INSTRUMENT_REIT", text)
