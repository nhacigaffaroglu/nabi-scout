from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from services.economic_classification_ingest import (
    ACTION_INSERT,
    ACTION_NOOP,
    ACTION_SKIP,
    SPRE_OPENFIGI_REIT_OBSERVATIONS,
    WRITE_GATE_FAIL,
    WRITE_GATE_PASS,
    persist_economic_ingest_plan,
    plan_spre_reit_economic_ingest,
)
from services.exposure_determinacy_diagnostics import eligible_fill_assets
from services.fund_intelligence_contract import FundHoldingRow, FundHoldingsSnapshotView
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.official_fund_holdings_client import OfficialHolding
from services.portfolio_economic_exposure import classify_instrument_exposure
from services.portfolio_intelligence_contract import PositionValuationRow
from services.reit_evidence_contract import (
    classify_from_name_or_fund,
    may_persist_reit_economic,
    may_persist_reit_fact,
)
from services.security_identity_contract import (
    ECONOMIC_LAYERS,
    EVIDENCE_OPENFIGI_SECURITY_TYPE,
    IDENTITY_FACT_SOURCES,
    SOURCE_ECONOMIC_CLASSIFICATION,
    SOURCE_IDENTIFIER_ALIAS,
    SOURCE_PROVIDER_EXPLICIT,
    SOURCE_REGULATOR_EXPLICIT,
    EconomicClassification,
    IdentifierAlias,
    canonical_id_from_figi,
)
from services.security_identity_service import (
    SecurityIdentityService,
    alias_fact,
    economic_fact,
    identity_service_from_security_master,
)
from services.security_master_contract import (
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_EQUITY,
    INSTRUMENT_FIXED_INCOME,
    INSTRUMENT_REIT,
    INSTRUMENT_UNKNOWN,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    SOURCE_US_LISTING,
    SecurityFact,
)
from services.security_master_service import SecurityMasterService
from services.sukuk_evidence_contract import classify_from_name_or_fund as sukuk_from_name


INGEST = Path("services/economic_classification_ingest.py")
IDENTITY = Path("services/security_identity_service.py")
LOOKTHROUGH = Path("services/portfolio_economic_exposure.py")


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


def _snapshot(symbol: str, holdings, coverage: float = 100.0) -> FundHoldingsSnapshotView:
    return FundHoldingsSnapshotView(
        fund_symbol=symbol,
        fund_type="etf",
        as_of="2026-08-29",
        source="sp_funds_official",
        coverage_pct=coverage,
        underlying_count=len(holdings),
        holdings=tuple(holdings),
        data_quality="good",
        limitation="",
    )


def _holding(ticker: str, weight: float, *, asset_type=None, name: str = "") -> FundHoldingRow:
    return FundHoldingRow(ticker, name or ticker, weight, asset_type, None, None)


def _official(
    ticker: str,
    sedol: str,
    weight: float,
    *,
    name: str = "Holding",
) -> OfficialHolding:
    return OfficialHolding(
        fund_symbol="SPRE",
        as_of=date(2026, 8, 29),
        ticker=ticker,
        cusip_raw=sedol,
        security_name=name,
        weight_pct=weight,
    )


def _observation_holdings() -> list[OfficialHolding]:
    return [
        _official(str(row["ticker"]), str(row["sedol"]), float(row["weight_pct"]))
        for row in SPRE_OPENFIGI_REIT_OBSERVATIONS
    ]


def _classification(
    figi: str,
    layer: str,
    *,
    source: str = SOURCE_PROVIDER_EXPLICIT,
    observed_at: str = "2026-08-29T00:00:00+00:00",
) -> EconomicClassification:
    return EconomicClassification(
        canonical_id=canonical_id_from_figi(figi),
        economic_layer=layer,
        source=source,
        evidence_type=EVIDENCE_OPENFIGI_SECURITY_TYPE,
        evidence_reference="test",
        status=RESOLUTION_RESOLVED,
        observed_at=observed_at,
        metadata={"figi": figi},
    )


class InstrumentIndependenceTests(unittest.TestCase):
    def test_instrument_type_independent_from_economic_layer(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(
            SecurityFact(
                "WELL",
                IDENTIFIER_TYPE_TICKER,
                INSTRUMENT_EQUITY,
                SOURCE_US_LISTING,
                "2026-08-29T00:00:00+00:00",
            )
        )
        master.repo.persist_facts(
            [
                economic_fact(
                    identifier="WELL",
                    identifier_type=IDENTIFIER_TYPE_TICKER,
                    classification=_classification("BBG000BPCQX6", "real_estate"),
                )
            ]
        )
        resolved = master.resolve_security("WELL")
        self.assertEqual(resolved.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(resolved.source, SOURCE_US_LISTING)
        identity = identity_service_from_security_master(master)
        layer = identity.resolve_economic_layer(["WELL"])
        self.assertEqual(layer.economic_layer, "real_estate")
        self.assertNotEqual(resolved.instrument_type.lower(), layer.economic_layer)

    def test_equity_and_real_estate_coexist(self) -> None:
        self.assertIn("real_estate", ECONOMIC_LAYERS)
        self.assertNotEqual(INSTRUMENT_EQUITY, "real_estate")
        self.assertFalse(may_persist_reit_fact())
        self.assertTrue(may_persist_reit_economic())

    def test_fixed_income_and_sukuk_synthetic_coexist(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(
            SecurityFact(
                "SYNTHSUK",
                IDENTIFIER_TYPE_TICKER,
                INSTRUMENT_FIXED_INCOME,
                SOURCE_PROVIDER_EXPLICIT,
                "2026-08-29T00:00:00+00:00",
            )
        )
        master.repo.persist_facts(
            [
                economic_fact(
                    identifier="SYNTHSUK",
                    identifier_type=IDENTIFIER_TYPE_TICKER,
                    classification=_classification("BBGTESTSUKUK1", "sukuk"),
                )
            ]
        )
        resolved = master.resolve_security("SYNTHSUK")
        self.assertEqual(resolved.instrument_type, INSTRUMENT_FIXED_INCOME)
        identity = identity_service_from_security_master(master)
        self.assertEqual(identity.resolve_economic_layer(["SYNTHSUK"]).economic_layer, "sukuk")
        snapshot = _snapshot(
            "FUNDZ",
            (_holding("SYNTHSUK", 100.0),),
        )
        view = classify_instrument_exposure(
            _etf("FUNDZ"),
            fund_snapshots={"FUNDZ": snapshot},
            security_master=master,
            identity_service=identity,
        )
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertAlmostEqual(buckets["sukuk"], 100.0)
        self.assertNotIn("fixed_income", buckets)

    def test_identity_sources_excluded_from_instrument_precedence(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.repo.persist_facts(
            [
                economic_fact(
                    identifier="WELL",
                    identifier_type=IDENTIFIER_TYPE_TICKER,
                    classification=_classification("BBG000BPCQX6", "real_estate"),
                )
            ]
        )
        resolved = master.resolve_security("WELL")
        self.assertEqual(resolved.instrument_type, INSTRUMENT_UNKNOWN)
        self.assertNotIn(resolved.source, IDENTITY_FACT_SOURCES)


class LookthroughMassTests(unittest.TestCase):
    def test_economic_layer_does_not_double_count(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(
            SecurityFact(
                "WELL",
                IDENTIFIER_TYPE_TICKER,
                INSTRUMENT_EQUITY,
                SOURCE_US_LISTING,
                "2026-08-29T00:00:00+00:00",
            )
        )
        master.repo.persist_facts(
            [
                economic_fact(
                    identifier="WELL",
                    identifier_type=IDENTIFIER_TYPE_TICKER,
                    classification=_classification("BBG000BPCQX6", "real_estate"),
                )
            ]
        )
        identity = identity_service_from_security_master(master)
        snapshot = _snapshot("FUNDX", (_holding("WELL", 100.0),))
        view = classify_instrument_exposure(
            _etf("FUNDX"),
            fund_snapshots={"FUNDX": snapshot},
            security_master=master,
            identity_service=identity,
        )
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertAlmostEqual(buckets["real_estate"], 100.0)
        self.assertNotIn("equity", buckets)
        self.assertAlmostEqual(sum(buckets.values()), 100.0)
        self.assertEqual(master.resolve_security("WELL").instrument_type, INSTRUMENT_EQUITY)

    def test_lookthrough_consumes_economic_classification(self) -> None:
        identity = SecurityIdentityService(
            aliases=(
                IdentifierAlias(
                    "IGBREIT MK",
                    IDENTIFIER_TYPE_TICKER,
                    "FIGI:BBG0038P24J8",
                    SOURCE_IDENTIFIER_ALIAS,
                    "2026-08-29T00:00:00+00:00",
                    {"figi": "BBG0038P24J8"},
                ),
            ),
            classifications=(_classification("BBG0038P24J8", "real_estate"),),
        )
        snapshot = _snapshot(
            "ANYFUND",
            (
                _holding("IGBREIT MK", 14.06),
                _holding("UNKNOWN1", 85.94),
            ),
        )
        view = classify_instrument_exposure(
            _etf("ANYFUND"),
            fund_snapshots={"ANYFUND": snapshot},
            identity_service=identity,
        )
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertAlmostEqual(buckets["real_estate"], 14.06)
        self.assertAlmostEqual(buckets["unknown"], 85.94)
        self.assertAlmostEqual(sum(buckets.values()), 100.0)

    def test_listing_equity_preserved_when_economic_is_real_estate(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        master.upsert_security_fact(
            SecurityFact(
                "PLD",
                IDENTIFIER_TYPE_TICKER,
                INSTRUMENT_EQUITY,
                SOURCE_US_LISTING,
                "2026-08-29T00:00:00+00:00",
            )
        )
        self.assertEqual(master.resolve_security("PLD").instrument_type, INSTRUMENT_EQUITY)
        self.assertNotEqual(master.resolve_security("PLD").instrument_type, INSTRUMENT_REIT)


class IdentifierAliasTests(unittest.TestCase):
    def test_ticker_sedol_figi_resolve_same_security(self) -> None:
        identity = SecurityIdentityService(
            aliases=(
                IdentifierAlias(
                    "IGBREIT MK",
                    IDENTIFIER_TYPE_TICKER,
                    "FIGI:BBG0038P24J8",
                    SOURCE_IDENTIFIER_ALIAS,
                    "2026-08-29T00:00:00+00:00",
                    {"figi": "BBG0038P24J8"},
                ),
                IdentifierAlias(
                    "B89JCF2",
                    IDENTIFIER_TYPE_SEDOL,
                    "FIGI:BBG0038P24J8",
                    SOURCE_IDENTIFIER_ALIAS,
                    "2026-08-29T00:00:00+00:00",
                    {"figi": "BBG0038P24J8"},
                ),
            ),
            classifications=(_classification("BBG0038P24J8", "real_estate"),),
        )
        for token in ("IGBREIT MK", "B89JCF2", "BBG0038P24J8"):
            resolved = identity.resolve_economic_layer([token])
            self.assertEqual(resolved.canonical_id, "FIGI:BBG0038P24J8")
            self.assertEqual(resolved.economic_layer, "real_estate")

    def test_ambiguous_alias_fail_closed(self) -> None:
        identity = SecurityIdentityService(
            aliases=(
                IdentifierAlias("DUP", IDENTIFIER_TYPE_TICKER, "FIGI:A", SOURCE_IDENTIFIER_ALIAS, "t", {}),
                IdentifierAlias("DUP", IDENTIFIER_TYPE_TICKER, "FIGI:B", SOURCE_IDENTIFIER_ALIAS, "t", {}),
            ),
            classifications=(
                _classification("A", "equity"),
                _classification("B", "real_estate"),
            ),
        )
        resolved = identity.resolve_economic_layer(["DUP"])
        self.assertEqual(resolved.status, RESOLUTION_CONFLICT)
        self.assertEqual(resolved.limitation, "AMBIGUOUS_ALIAS")
        self.assertIsNone(resolved.economic_layer)

    def test_same_rank_economic_conflict_fail_closed(self) -> None:
        identity = SecurityIdentityService(
            aliases=(
                IdentifierAlias("X", IDENTIFIER_TYPE_TICKER, "FIGI:X", SOURCE_IDENTIFIER_ALIAS, "t", {}),
            ),
            classifications=(
                EconomicClassification(
                    "FIGI:X",
                    "equity",
                    SOURCE_PROVIDER_EXPLICIT,
                    "a",
                    "a",
                    RESOLUTION_RESOLVED,
                    "t",
                ),
                EconomicClassification(
                    "FIGI:X",
                    "real_estate",
                    SOURCE_PROVIDER_EXPLICIT,
                    "b",
                    "b",
                    RESOLUTION_RESOLVED,
                    "t",
                ),
            ),
        )
        resolved = identity.resolve_economic_layer(["X"])
        self.assertEqual(resolved.status, RESOLUTION_CONFLICT)
        self.assertEqual(resolved.limitation, "ECONOMIC_SOURCE_CONFLICT")

    def test_figi_is_not_a_security_master_identifier_type(self) -> None:
        with self.assertRaises(ValueError):
            alias_fact(
                identifier="BBG0038P24J8",
                identifier_type="FIGI",
                canonical_id="FIGI:BBG0038P24J8",
                observed_at="2026-08-29T00:00:00+00:00",
            )


class EvidenceContractTests(unittest.TestCase):
    def test_name_joins_and_fund_membership_forbidden(self) -> None:
        self.assertEqual(classify_from_name_or_fund("IGB Real Estate Investment Trust", "SPRE"), "UNKNOWN")
        self.assertEqual(sukuk_from_name("SP Funds Sukuk ETF", "SPSK"), "UNKNOWN")
        ingest = INGEST.read_text(encoding="utf-8")
        identity = IDENTITY.read_text(encoding="utf-8")
        lookthrough = LOOKTHROUGH.read_text(encoding="utf-8")
        self.assertNotIn("security_name ==", ingest)
        self.assertNotIn("fuzzy", ingest.lower())
        self.assertIn("No name joins", identity)
        self.assertNotIn("if fund_symbol", lookthrough.lower())

    def test_provider_reit_explicit_only(self) -> None:
        extras = [
            _official("WELL", "B8BJ4F5", 10.0, name="Welltower REIT"),
            *[_official("PAD%02d" % index, "XXXXXX%d" % index, 1.0) for index in range(23)],
        ]
        plan = plan_spre_reit_economic_ingest(_observation_holdings() + extras)
        self.assertEqual(plan.exact, 6)
        self.assertEqual(plan.ambiguous, 0)
        self.assertEqual(plan.unmapped, 24)
        self.assertEqual(sum(1 for row in plan.rows if row.action == ACTION_INSERT), 6)
        self.assertAlmostEqual(sum(row.weight_pct for row in plan.rows if row.action == ACTION_INSERT), 14.06)
        self.assertTrue(all(row.instrument_type == "UNKNOWN" for row in plan.rows if row.action == ACTION_INSERT))
        self.assertTrue(all(row.economic_layer == "real_estate" for row in plan.rows if row.action == ACTION_INSERT))
        self.assertFalse(any(fact.instrument_type == INSTRUMENT_REIT for fact in plan.facts))

    def test_sedol_mismatch_is_ambiguous_not_name_join(self) -> None:
        wrong = [_official("IGBREIT MK", "B000000", 4.01, name="IGB Real Estate Investment Trust")]
        plan = plan_spre_reit_economic_ingest(wrong, observations=SPRE_OPENFIGI_REIT_OBSERVATIONS[:1])
        self.assertEqual(plan.rows[0].action, ACTION_SKIP)
        self.assertEqual(plan.rows[0].reason, "SEDOL_NOT_EXACT")
        self.assertEqual(plan.write_gate, WRITE_GATE_FAIL)

    def test_ingest_idempotency(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        plan = plan_spre_reit_economic_ingest(_observation_holdings())
        self.assertEqual(plan.write_gate, WRITE_GATE_PASS)
        first = persist_economic_ingest_plan(plan, security_master=master)
        self.assertEqual(first.inserted, 12)
        self.assertEqual(first.updated, 0)
        replay = plan_spre_reit_economic_ingest(
            _observation_holdings(),
            existing_rows=master.repo.list_all(),
        )
        self.assertTrue(all(row.action == ACTION_NOOP for row in replay.rows if row.action != ACTION_SKIP))
        second = persist_economic_ingest_plan(replay, security_master=master)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.updated, 0)
        self.assertEqual(second.unchanged, 12)
        self.assertEqual(master.repo.count(), 12)

    def test_persist_refuses_failed_gate(self) -> None:
        master = SecurityMasterService(include_canonical_static=False)
        plan = plan_spre_reit_economic_ingest([])
        self.assertEqual(plan.write_gate, WRITE_GATE_FAIL)
        with self.assertRaises(RuntimeError):
            persist_economic_ingest_plan(plan, security_master=master)


class ParticipationAndHybridTests(unittest.TestCase):
    def test_spre_kontrol_et_is_not_new_money_filler(self) -> None:
        identity = SecurityIdentityService(
            aliases=(
                IdentifierAlias(
                    "IGBREIT MK",
                    IDENTIFIER_TYPE_TICKER,
                    "FIGI:BBG0038P24J8",
                    SOURCE_IDENTIFIER_ALIAS,
                    "t",
                    {"figi": "BBG0038P24J8"},
                ),
            ),
            classifications=(_classification("BBG0038P24J8", "real_estate"),),
        )
        snapshot = _snapshot("SPRE", (_holding("IGBREIT MK", 14.06), _holding("OTHER", 85.94)))
        view = classify_instrument_exposure(
            _etf("SPRE"),
            fund_snapshots={"SPRE": snapshot},
            identity_service=identity,
        )
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertIn("real_estate", buckets)
        fills = eligible_fill_assets(
            (view,),
            extra_symbols=({"symbol": "SPRE", "participation_status": "Kontrol Et"},),
        )
        self.assertEqual(fills, ())

    def test_hybrid_remains_off_by_default(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        self.assertFalse(resolve_hybrid_allocation_policy(None).enabled)


class RegulatorPrecedenceTests(unittest.TestCase):
    def test_regulator_outranks_provider_without_inheriting_instrument_ranks(self) -> None:
        identity = SecurityIdentityService(
            aliases=(
                IdentifierAlias("Y", IDENTIFIER_TYPE_TICKER, "FIGI:Y", SOURCE_IDENTIFIER_ALIAS, "t", {}),
            ),
            classifications=(
                _classification("Y", "equity", source=SOURCE_PROVIDER_EXPLICIT),
                EconomicClassification(
                    "FIGI:Y",
                    "real_estate",
                    SOURCE_REGULATOR_EXPLICIT,
                    "reg",
                    "reg",
                    RESOLUTION_RESOLVED,
                    "t",
                ),
            ),
        )
        resolved = identity.resolve_economic_layer(["Y"])
        self.assertEqual(resolved.economic_layer, "real_estate")
        self.assertEqual(resolved.source, SOURCE_REGULATOR_EXPLICIT)
