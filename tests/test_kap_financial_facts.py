from __future__ import annotations

import unittest
from pathlib import Path

from services.kap_financial_bridge import (
    MISSING_REQUIRED_FACT,
    KapIdentityError,
    build_kap_normalized_bundle,
    is_us_symbol_blocked_from_kap,
    kap_security_facts_payload,
    participation_inputs_from_kap,
    resolve_bist_financial_identity,
)
from services.kap_financial_contract import (
    ACCOUNT_REVENUE,
    KAP_ACCESS_CREDENTIAL_BLOCKED,
    KapFinancialAccessError,
    KapRawFinancialLine,
    NATURE_FLOW,
    PERIOD_FY,
    PERIOD_Q,
    PERIOD_YTD,
    STATEMENT_INCOME,
    fetch_official_kap_financials,
    resolve_kap_financial_access,
)
from services.kap_financial_normalization import (
    map_account_code,
    normalize_raw_line,
    period_compatibility,
    resolve_unit_scale,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_security_decision_contract import (
    DECISION_REVIEW,
    PortfolioSecurityContext,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import (
    AUTHORITY_KAP,
    AUTHORITY_SEC,
    PERIOD_INCOMPATIBLE,
    PERIOD_TTM,
    STATE_ATTRACTIVE,
)
from services.security_master_contract import INSTRUMENT_EQUITY, RESOLUTION_RESOLVED, SOURCE_BIST
from services.security_master_service import SecurityMasterService
from tests.fixtures.kap_financial_pilot import (
    FIXTURE_DISCLAIMER,
    PILOT_RAW_LINES,
    asels_raw_lines,
    bimas_raw_lines,
    tuprs_raw_lines,
)


BRIDGE = Path("services/kap_financial_bridge.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")


def _bundle(symbol: str):
    return build_kap_normalized_bundle(symbol, PILOT_RAW_LINES[symbol]())


class KapAccessTests(unittest.TestCase):
    def test_financial_endpoint_unknown_and_fetch_closed(self) -> None:
        status = resolve_kap_financial_access()
        self.assertEqual(status.status, KAP_ACCESS_CREDENTIAL_BLOCKED)
        self.assertFalse(status.live_calls_allowed)
        self.assertFalse(status.credentials_configured)
        self.assertIsNone(status.financial_endpoint)
        self.assertEqual(status.official_client, "KapRestClient")
        self.assertIn("KapDisclosureAdapter", status.existing_adapter)
        with self.assertRaises(KapFinancialAccessError):
            fetch_official_kap_financials("ASELS")


class RawContractTests(unittest.TestCase):
    def test_raw_line_preserves_raw_value(self) -> None:
        line = asels_raw_lines()[0]
        self.assertEqual(line.raw_value, 120.0)
        self.assertNotIn("normalized_value", line.to_dict())
        self.assertEqual(line.source, "KAP")
        self.assertIn("TEST-ONLY", line.provenance["disclaimer"])

    def test_unknown_account_is_unmapped(self) -> None:
        self.assertIsNone(map_account_code("NABI_TEST.UNKNOWN.WIDGETS"))
        self.assertIsNone(map_account_code(""))
        self.assertIsNone(map_account_code(None))
        unknown = next(
            item for item in asels_raw_lines() if item.account_code == "NABI_TEST.UNKNOWN.WIDGETS"
        )
        self.assertIsNone(normalize_raw_line(unknown))

    def test_label_without_code_is_unmapped(self) -> None:
        line = KapRawFinancialLine(
            symbol="ASELS",
            statement_type=STATEMENT_INCOME,
            reporting_period=PERIOD_FY,
            fact_nature=NATURE_FLOW,
            currency="TRY",
            account_label="Hasılat / Revenue",
            account_code=None,
            raw_value=10.0,
            unit_scale=1,
            unit_label="TRY",
        )
        self.assertIsNone(normalize_raw_line(line))


class PeriodAndUnitTests(unittest.TestCase):
    def test_ytd_is_not_ttm(self) -> None:
        self.assertEqual(period_compatibility(PERIOD_YTD, PERIOD_TTM), PERIOD_INCOMPATIBLE)
        self.assertEqual(period_compatibility(PERIOD_YTD, PERIOD_FY), PERIOD_INCOMPATIBLE)
        self.assertEqual(period_compatibility(PERIOD_FY, PERIOD_Q), PERIOD_INCOMPATIBLE)
        self.assertEqual(period_compatibility(PERIOD_FY, PERIOD_FY), PERIOD_FY)

    def test_explicit_scale_only(self) -> None:
        million = asels_raw_lines()[0]
        self.assertEqual(resolve_unit_scale(million), 1_000_000)
        unlabeled = KapRawFinancialLine(
            symbol="ASELS",
            statement_type=STATEMENT_INCOME,
            reporting_period=PERIOD_FY,
            fact_nature=NATURE_FLOW,
            currency="TRY",
            account_label="x",
            account_code=ACCOUNT_REVENUE,
            raw_value=5.0,
            unit_scale=None,
            unit_label="",
        )
        self.assertIsNone(resolve_unit_scale(unlabeled))
        self.assertIsNone(normalize_raw_line(unlabeled))

    def test_currency_preserved_not_hardcoded(self) -> None:
        usd = KapRawFinancialLine(
            symbol="ASELS",
            statement_type=STATEMENT_INCOME,
            reporting_period=PERIOD_FY,
            fact_nature=NATURE_FLOW,
            currency="USD",
            account_label="revenue",
            account_code=ACCOUNT_REVENUE,
            raw_value=2.0,
            unit_scale=1,
            unit_label="USD",
        )
        fact = normalize_raw_line(usd)
        self.assertIsNotNone(fact)
        self.assertEqual(fact.currency, "USD")
        self.assertEqual(fact.normalized_value, 2.0)


class NormalizationTests(unittest.TestCase):
    def test_million_and_thousand_scales(self) -> None:
        asels = _bundle("ASELS")
        revenue = next(item for item in asels.mapped if item.field == "revenue" and item.period_kind == PERIOD_FY)
        self.assertEqual(revenue.raw_value, 120.0)
        self.assertEqual(revenue.raw_unit_scale, 1_000_000)
        self.assertEqual(revenue.normalized_value, 120_000_000)
        self.assertEqual(revenue.currency, "TRY")
        bimas = _bundle("BIMAS")
        revenue = next(item for item in bimas.mapped if item.field == "revenue" and item.period_kind == PERIOD_FY)
        self.assertEqual(revenue.normalized_value, 900_000)
        ytd = next(item for item in bimas.mapped if item.field == "revenue" and item.period_kind == PERIOD_YTD)
        self.assertEqual(ytd.period_kind, PERIOD_YTD)
        self.assertNotEqual(ytd.period_kind, PERIOD_TTM)

    def test_missing_is_not_zero(self) -> None:
        bimas = _bundle("BIMAS")
        self.assertIsNone(bimas.fact("operating_income"))
        self.assertNotEqual(bimas.fact("operating_income"), 0)

    def test_incompatible_flow_and_balance_do_not_derive_roa(self) -> None:
        tuprs = _bundle("TUPRS")
        self.assertEqual(tuprs.period_compatibility, PERIOD_INCOMPATIBLE)
        roa = next(item for item in tuprs.derived if item.field == "roa")
        self.assertIsNone(roa.value)
        self.assertIn(roa.limitation, {"MISSING_INPUT", "PERIOD_INCOMPATIBLE"})

    def test_compatible_fy_derives_roa(self) -> None:
        asels = _bundle("ASELS")
        roa = next(item for item in asels.derived if item.field == "roa" and item.period_compatibility == PERIOD_FY)
        self.assertAlmostEqual(roa.value, 12_000_000 / 400_000_000 * 100.0)
        self.assertEqual(roa.numerator_field, "net_income")
        self.assertEqual(roa.denominator_field, "total_assets")


class SecurityFactsKapTests(unittest.TestCase):
    def test_bist_kap_authority_and_identity(self) -> None:
        bundle = _bundle("ASELS")
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=bundle,
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.instrument_type, INSTRUMENT_EQUITY)
        self.assertEqual(facts.currency, "TRY")
        self.assertEqual(facts.revenue, 120_000_000)
        self.assertEqual(facts.total_assets, 400_000_000)
        self.assertEqual(facts.authority_status, AUTHORITY_KAP)
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["revenue"].authority, AUTHORITY_KAP)
        identity = resolve_bist_financial_identity("ASELS")
        self.assertEqual(identity.source, SOURCE_BIST)

    def test_kap_outranks_candidate_on_bist(self) -> None:
        facts = SecurityFactsService().build(
            "ASELS",
            kap_financials=_bundle("ASELS"),
            candidate={"revenue": 1, "currency": "TRY"},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.revenue, 120_000_000)
        self.assertNotEqual(facts.revenue, 1)

    def test_ytd_does_not_enter_security_facts(self) -> None:
        bundle = _bundle("BIMAS")
        payload = kap_security_facts_payload(bundle)
        self.assertEqual(payload["revenue"], 900_000)
        facts = SecurityFactsService().build(
            "BIMAS",
            kap_financials=bundle,
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.revenue, 900_000)
        self.assertIsNone(facts.operating_income)

    def test_us_sec_unchanged_and_kap_does_not_leak(self) -> None:
        self.assertTrue(is_us_symbol_blocked_from_kap("AAPL"))
        self.assertTrue(is_us_symbol_blocked_from_kap("CRM"))
        facts = SecurityFactsService().build(
            "AAPL",
            kap_financials=_bundle("ASELS"),
            sec_financials={"revenue": 400, "financial_currency": "USD", "financial_period_end": "2025-09-27"},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.revenue, 400)
        self.assertEqual(facts.currency, "USD")
        by_field = {item.field: item for item in facts.provenance}
        self.assertEqual(by_field["revenue"].authority, AUTHORITY_SEC)
        with self.assertRaises(KapIdentityError):
            build_kap_normalized_bundle("AAPL", asels_raw_lines())


class ParticipationBridgeTests(unittest.TestCase):
    def test_inputs_without_verdict(self) -> None:
        inputs, missing = participation_inputs_from_kap(_bundle("ASELS"))
        self.assertEqual(inputs.symbol, "ASELS")
        self.assertEqual(inputs.total_revenue, 120_000_000)
        self.assertEqual(inputs.total_assets, 400_000_000)
        self.assertEqual(inputs.total_debt, 80_000_000)
        self.assertEqual(inputs.cash, 40_000_000)
        self.assertIsNone(inputs.non_permissible_revenue)
        self.assertIsNone(inputs.cash_and_interest_bearing_securities)
        self.assertIsNone(inputs.accounts_receivable)
        self.assertTrue(any(item.startswith(MISSING_REQUIRED_FACT) for item in missing))
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_financial_rules", source)
        self.assertNotIn("Uygun", source)
        self.assertNotIn("evaluate_participation", source.lower())

    def test_missing_required_facts_are_named(self) -> None:
        _, missing = participation_inputs_from_kap(_bundle("TUPRS"))
        self.assertIn(f"{MISSING_REQUIRED_FACT}:non_permissible_revenue", missing)
        self.assertIn(f"{MISSING_REQUIRED_FACT}:market_capitalization", missing)


class DownstreamAndRegressionTests(unittest.TestCase):
    def test_8e_still_fail_closed(self) -> None:
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    si_state=STATE_ATTRACTIVE,
                    si_score=72.0,
                    is_holding=True,
                    quantity=10.0,
                    market_value=2500.0,
                    portfolio_weight=5.0,
                    concentration_ceiling=CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_REVIEW)
            self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
            self.assertIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, result.blocking_reasons)
            self.assertFalse(result.exposure_increase_allowed)
        self.assertIn("supports_portfolio_decision", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn("if symbol in BIST_PORTFOLIO_SYMBOLS", ENGINE.read_text(encoding="utf-8"))

    def test_pilot_identity_remains_bist_listing(self) -> None:
        master = SecurityMasterService()
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            resolution = master.resolve_security(symbol)
            self.assertEqual(resolution.status, RESOLUTION_RESOLVED)
            self.assertEqual(resolution.source, SOURCE_BIST)
            self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)

    def test_crm_sec_path_untouched(self) -> None:
        facts = SecurityFactsService().build(
            "CRM",
            sec_financials={"revenue": 100, "roic": 20, "financial_currency": "USD"},
            allow_sec_cache_replay=False,
        )
        self.assertEqual(facts.revenue, 100)
        self.assertEqual(facts.authority_status, AUTHORITY_SEC)

    def test_fixtures_are_marked_synthetic(self) -> None:
        self.assertIn("TEST-ONLY", FIXTURE_DISCLAIMER)
        self.assertIn("synthetic", FIXTURE_DISCLAIMER.lower())
        self.assertIn("not official", FIXTURE_DISCLAIMER.lower())


if __name__ == "__main__":
    unittest.main()
