from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.official_fund_holdings_client import OfficialHolding
from services.security_identifier_match import match_identifier_to_security_master
from services.security_identifier_validation import (
    assess_identifier,
    assess_official_holding_identifiers,
    cusip_check_digit,
    is_listing_ticker_format,
    is_valid_cusip,
    is_valid_isin,
    is_valid_sedol,
    sedol_check_digit,
)
from services.security_master_contract import (
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_EQUITY,
    INSTRUMENT_SUKUK,
    SOURCE_US_LISTING,
    SecurityFact,
)
from services.security_master_service import SecurityMasterService
from services.spsk_underlying_resolution import (
    WRITE_NONE,
    WRITE_SKIP_CONFLICT,
    WRITE_SKIP_NO_EVIDENCE,
    dry_run_spsk_holdings,
    resolve_official_holding,
)
from services.sukuk_evidence_contract import (
    classify_from_name_or_fund,
    explicit_instrument_from_structured_type,
    name_is_not_evidence,
    spsk_membership_is_not_evidence,
)

VALIDATION = Path("services/security_identifier_validation.py")
CONTRACT = Path("services/sukuk_evidence_contract.py")
RESOLUTION = Path("services/spsk_underlying_resolution.py")
HYBRID = Path("services/hybrid_exposure_allocation_policy.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")


def _holding(**kwargs) -> OfficialHolding:
    defaults = dict(
        fund_symbol="SPSK",
        as_of=date(2026, 8, 28),
        ticker="BT6MTT4",
        cusip_raw="BT6MTT4",
        security_name="KSA Sukuk Ltd",
        weight_pct=1.25,
    )
    defaults.update(kwargs)
    return OfficialHolding(**defaults)


def _fact(identifier, identifier_type, instrument_type, source=SOURCE_US_LISTING) -> SecurityFact:
    return SecurityFact(
        identifier=identifier,
        identifier_type=identifier_type,
        instrument_type=instrument_type,
        source=source,
        observed_at="2026-01-01T00:00:00+00:00",
    )


class IdentifierValidationTests(unittest.TestCase):
    def test_missing_and_unverified(self) -> None:
        self.assertEqual(assess_identifier("").usability, "MISSING")
        self.assertEqual(assess_identifier("NOTANID").usability, "UNVERIFIED_IDENTIFIER")
        self.assertIsNone(assess_identifier("NOTANID").identifier_type)

    def test_valid_cusip_check_digit(self) -> None:
        self.assertEqual(cusip_check_digit("03783310"), "0")
        self.assertTrue(is_valid_cusip("037833100"))
        self.assertFalse(is_valid_cusip("037833101"))
        self.assertEqual(assess_identifier("037833100").usability, "VALID_CUSIP")

    def test_valid_sedol_check_digit(self) -> None:
        body = "B0YBKJ"
        digit = sedol_check_digit(body)
        self.assertIsNotNone(digit)
        self.assertTrue(is_valid_sedol(body + digit))
        self.assertFalse(is_valid_sedol(body + str((int(digit) + 1) % 10)))

    def test_valid_isin_and_listing_ticker(self) -> None:
        self.assertTrue(is_valid_isin("US0378331005"))
        self.assertFalse(is_valid_isin("US0378331006"))
        self.assertTrue(is_listing_ticker_format("AAPL"))
        self.assertTrue(is_listing_ticker_format("BRK.B"))
        self.assertFalse(is_listing_ticker_format("BT6MTT4"))
        self.assertEqual(assess_identifier("AAPL").usability, "LISTING_TICKER")

    def test_cusip_column_is_not_assumed_cusip(self) -> None:
        judged = assess_official_holding_identifiers(ticker="AAPL", cusip_raw="NOTANID")
        self.assertNotEqual(judged.usability, "VALID_CUSIP")
        self.assertEqual(assess_identifier("NOTANID").usability, "UNVERIFIED_IDENTIFIER")
        self.assertEqual(assess_identifier("BT6MTT4").usability, "VALID_SEDOL")


class SecurityMasterMatchTests(unittest.TestCase):
    def test_exact_compatible_type_only(self) -> None:
        master = SecurityMasterService()
        master.upsert_security_fact(_fact("AAPL", IDENTIFIER_TYPE_TICKER, INSTRUMENT_EQUITY))
        exact = match_identifier_to_security_master("AAPL", security_master=master)
        self.assertEqual(exact.status, "EXACT")
        sedol_body = "B0YBKJ"
        sedol = sedol_body + sedol_check_digit(sedol_body)
        master.upsert_security_fact(_fact(sedol, IDENTIFIER_TYPE_SEDOL, INSTRUMENT_SUKUK))
        crossed = match_identifier_to_security_master(
            sedol,
            security_master=master,
        )
        self.assertEqual(crossed.status, "EXACT")
        self.assertEqual(crossed.assessment.identifier_type, "SEDOL")

    def test_unverified_does_not_match_ticker_fact(self) -> None:
        master = SecurityMasterService()
        master.upsert_security_fact(_fact("NOTANID", IDENTIFIER_TYPE_TICKER, INSTRUMENT_EQUITY))
        judged = match_identifier_to_security_master("NOTANID", security_master=master)
        self.assertEqual(judged.status, "UNMATCHED")


class EvidenceContractTests(unittest.TestCase):
    def test_no_name_or_fund_inference(self) -> None:
        self.assertTrue(name_is_not_evidence("KSA Sukuk Ltd"))
        self.assertTrue(spsk_membership_is_not_evidence("SPSK"))
        self.assertEqual(classify_from_name_or_fund("KSA Sukuk Ltd", "SPSK"), "UNKNOWN")
        self.assertIsNone(explicit_instrument_from_structured_type("certificate"))
        self.assertIsNone(explicit_instrument_from_structured_type("trust"))
        self.assertIsNone(explicit_instrument_from_structured_type("islamic bond"))
        self.assertEqual(explicit_instrument_from_structured_type("sukuk"), "SUKUK")
        self.assertEqual(explicit_instrument_from_structured_type("fixed_income"), "FIXED_INCOME")

    def test_source_has_no_spsk_equals_sukuk(self) -> None:
        for path in (CONTRACT, RESOLUTION, VALIDATION):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("SPSK = SUKUK", text)
            self.assertNotIn('if fund_symbol == "SPSK"', text)


class DryRunAndConflictTests(unittest.TestCase):
    def test_name_does_not_classify_and_no_write(self) -> None:
        master = SecurityMasterService()
        row = resolve_official_holding(_holding(), security_master=master)
        self.assertEqual(row.instrument_type, "UNKNOWN")
        self.assertEqual(row.write_action, WRITE_SKIP_NO_EVIDENCE)
        self.assertIsNone(row.economic_layer)

    def test_existing_sm_fact_is_not_rewritten(self) -> None:
        master = SecurityMasterService()
        master.upsert_security_fact(_fact("AAPL", IDENTIFIER_TYPE_TICKER, INSTRUMENT_EQUITY))
        row = resolve_official_holding(
            _holding(ticker="AAPL", cusip_raw="", security_name="Apple"),
            security_master=master,
        )
        self.assertEqual(row.instrument_type, "EQUITY")
        self.assertEqual(row.write_action, WRITE_NONE)
        self.assertEqual(row.economic_layer, "equity")

    def test_conflict_fail_closed(self) -> None:
        master = SecurityMasterService()
        master.upsert_security_fact(_fact("AAPL", IDENTIFIER_TYPE_TICKER, INSTRUMENT_EQUITY))
        sedol = "B0YBKJ" + sedol_check_digit("B0YBKJ")
        master.upsert_security_fact(_fact(sedol, IDENTIFIER_TYPE_SEDOL, INSTRUMENT_SUKUK))
        row = resolve_official_holding(
            _holding(ticker="AAPL", cusip_raw=sedol),
            security_master=master,
        )
        self.assertEqual(row.write_action, WRITE_SKIP_CONFLICT)
        self.assertEqual(row.instrument_type, "UNKNOWN")

    def test_dry_run_keeps_unknown_weight(self) -> None:
        master = SecurityMasterService()
        report = dry_run_spsk_holdings(
            (
                _holding(ticker="AAA", cusip_raw="", weight_pct=40.0, security_name="One"),
                _holding(ticker="BBB", cusip_raw="", weight_pct=60.0, security_name="Two"),
            ),
            security_master=master,
        )
        self.assertAlmostEqual(report.instrument_weight.get("UNKNOWN", 0.0), 100.0)
        self.assertAlmostEqual(report.unmatched_weight, 100.0)
        self.assertEqual(report.match_status.get("UNMATCHED"), 2)


class HybridAndInvariantSourceTests(unittest.TestCase):
    def test_hybrid_remains_off_and_policy_untouched(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        hybrid = HYBRID.read_text(encoding="utf-8")
        self.assertIn("enable_hybrid_exposure_allocation: bool = False", hybrid)
        self.assertNotIn("SPSK", hybrid)

    def test_new_money_default_still_strict(self) -> None:
        source = NEW_MONEY.read_text(encoding="utf-8")
        self.assertIn("enable_hybrid_exposure_allocation: Optional[bool] = None", source)
        self.assertNotIn("SPSK = SUKUK", source)


class LookthroughAndCeilingTests(unittest.TestCase):
    def test_lookthrough_reclassifies_only_with_sm_fact(self) -> None:
        from services.fund_intelligence_contract import FundHoldingRow
        from services.security_master_service import summarize_holding_coverage

        sedol = "B0YBKJ" + sedol_check_digit("B0YBKJ")
        holdings = [
            FundHoldingRow(sedol, "KSA Sukuk Ltd", 100.0, None, None, None),
        ]
        empty = summarize_holding_coverage(holdings, security_master=SecurityMasterService())
        self.assertEqual(empty["UNKNOWN"], 100.0)
        master = SecurityMasterService()
        master.upsert_security_fact(_fact(sedol, IDENTIFIER_TYPE_SEDOL, INSTRUMENT_SUKUK))
        classified = summarize_holding_coverage(holdings, security_master=master)
        self.assertEqual(classified["classified_SUKUK"], 100.0)
        self.assertEqual(classified["UNKNOWN"], 0.0)

    def test_projected_unknown_stays_above_ceiling_without_evidence(self) -> None:
        report = dry_run_spsk_holdings(
            (_holding(ticker="NOTANID", cusip_raw="NOTANID", weight_pct=100.07),),
            security_master=SecurityMasterService(),
        )
        before = 3.3166
        after = before
        self.assertGreater(after, 1.00)
        self.assertAlmostEqual(report.instrument_weight["UNKNOWN"], 100.07)

    def test_official_schema_has_no_instrument_type(self) -> None:
        from services.official_fund_holdings_client import REQUIRED_COLUMNS

        self.assertNotIn("AssetType", REQUIRED_COLUMNS)
        self.assertNotIn("InstrumentType", REQUIRED_COLUMNS)
        self.assertNotIn("SecurityType", REQUIRED_COLUMNS)


class IdempotencyContractTests(unittest.TestCase):
    def test_existing_fact_upsert_is_identity(self) -> None:
        master = SecurityMasterService()
        fact = _fact("AAPL", IDENTIFIER_TYPE_TICKER, INSTRUMENT_EQUITY)
        first = master.upsert_security_fact(fact)
        second = master.upsert_security_fact(fact)
        self.assertEqual(
            (first.get("identifier"), first.get("instrument_type"), first.get("source")),
            (second.get("identifier"), second.get("instrument_type"), second.get("source")),
        )


if __name__ == "__main__":
    unittest.main()
