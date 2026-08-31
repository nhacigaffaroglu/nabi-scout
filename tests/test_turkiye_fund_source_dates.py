from __future__ import annotations

import unittest
from pathlib import Path

from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import PILOT_FUND_SYMBOLS, PILOT_TEFAS_FUND_CODES
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider
from services.official_turkiye_fund_evidence import load_kap_official_bundle
from services.official_turkiye_fund_participation import evaluate_pilot_participation
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import DECISION_WATCH
from services.turkiye_fund_refresh_contract import (
    LAYER_ECONOMIC_EXPOSURE,
    LAYER_EIGHT_E,
    LAYER_FUND_INTELLIGENCE,
    LAYER_IDENTITY,
    LAYER_PARTICIPATION,
)
from services.turkiye_fund_refresh_orchestrator import (
    compute_turkiye_fund_snapshots,
    run_turkiye_fund_refresh,
)
from services.turkiye_fund_source_dates import (
    FutureSourceDateError,
    SEMANTIC_DOCUMENT_VERSION_DATE,
    SEMANTIC_EFFECTIVE_AT,
    SEMANTIC_PUBLISHED_AT,
    SEMANTIC_REPORT_PERIOD,
    SEMANTIC_SOURCE_AS_OF,
    assert_current_evidence_date,
    filename_period,
    layer_idempotency_dates,
    parse_official_date,
    parse_pdf_info_date,
    resolve_kap_document_date,
    source_as_of_bundle,
)
from services.wealth_new_money_allocation import allocate_new_money

CALCULATED_AT = "2026-08-30T21:00:00+00:00"
BIST = Path("services/bist_refresh_contract.py")
US_SI = Path("services/security_intelligence_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
DATES = Path("services/turkiye_fund_source_dates.py")
FROZEN_FI = {
    "AIS": (70.39, "WATCH"),
    "ZPE": (66.32, "WATCH"),
    "IAT": (60.49, "NEUTRAL"),
}


class TurkiyeFundSourceDateTests(unittest.TestCase):
    def test_dd_mm_yyyy_parsing(self) -> None:
        self.assertEqual(parse_official_date("27/02/2026"), "2026-02-27")
        self.assertEqual(parse_official_date("27.02.2026"), "2026-02-27")
        self.assertEqual(parse_official_date("27/02/26"), "2026-02-27")
        self.assertEqual(parse_official_date("27.02.26"), "2026-02-27")
        self.assertEqual(parse_official_date("27.02.27"), "2027-02-27")
        self.assertEqual(parse_official_date("2026-02-27T08:09:19+03:00"), "2026-02-27")
        self.assertEqual(parse_pdf_info_date("D:20260227133056+03'00'"), "2026-02-27")
        self.assertNotEqual(parse_official_date("27/02/26"), "2027-02-26")

    def test_structured_kap_date_precedes_filename_and_pdf(self) -> None:
        value, semantic, origin = resolve_kap_document_date(
            structured_publish_date="27.02.2026",
            pdf_xmp_date="2027-02-27T00:00:00",
            filename="IAT_2027.02.pdf",
        )
        self.assertEqual(value, "2026-02-27")
        self.assertEqual(semantic, SEMANTIC_PUBLISHED_AT)
        self.assertEqual(origin, "structured_kap")
        self.assertEqual(filename_period("IAT_2026.07.pdf"), "2026-07")
        empty, empty_sem, origin = resolve_kap_document_date(filename="IAT_2026.07.pdf")
        self.assertIsNone(empty)
        self.assertIsNone(empty_sem)
        self.assertEqual(origin, "unresolved")

    def test_future_publication_is_rejected(self) -> None:
        with self.assertRaises(FutureSourceDateError):
            assert_current_evidence_date(
                "2027-02-27",
                calculated_at=CALCULATED_AT,
                semantic=SEMANTIC_PUBLISHED_AT,
                field="kap_mandate",
            )
        bundle = source_as_of_bundle(
            tefas_price="2026-08-28",
            kap_pdr="2026-07",
            kap_mandate="2027-02-27",
            kap_izahname="2022-07-08",
            calculated_at=CALCULATED_AT,
        )
        self.assertIsNone(bundle["kap_mandate"])
        self.assertEqual(bundle["rejected"][0]["value"], "2027-02-27")
        self.assertNotEqual(bundle["tefas_price"], CALCULATED_AT)

    def test_future_effective_date_is_separated(self) -> None:
        kept = assert_current_evidence_date(
            "2027-02-27",
            calculated_at=CALCULATED_AT,
            semantic=SEMANTIC_EFFECTIVE_AT,
            field="kap_mandate_effective_at",
        )
        self.assertEqual(kept, "2027-02-27")
        bundle = source_as_of_bundle(
            tefas_price="2026-08-28",
            kap_pdr="2026-07",
            kap_mandate="2026-02-27",
            kap_izahname="2022-07-08",
            kap_mandate_effective_at="2027-02-27",
            calculated_at=CALCULATED_AT,
        )
        self.assertEqual(bundle["kap_mandate"], "2026-02-27")
        self.assertEqual(bundle["date_model"]["kap_mandate"]["effective_at"], "2027-02-27")
        self.assertEqual(bundle["date_model"]["kap_mandate"]["semantic"], SEMANTIC_PUBLISHED_AT)
        self.assertNotIn("rejected", bundle)

    def test_report_period_is_not_a_publication_date(self) -> None:
        bundle = source_as_of_bundle(
            tefas_price="2026-08-28",
            kap_pdr="2026-07",
            kap_mandate="2026-02-27",
            kap_izahname="2022-07-08",
            kap_pdr_published_at="05.08.2026",
            calculated_at=CALCULATED_AT,
        )
        self.assertEqual(bundle["kap_pdr"], "2026-07")
        self.assertEqual(bundle["date_model"]["kap_pdr"]["semantic"], SEMANTIC_REPORT_PERIOD)
        self.assertEqual(bundle["date_model"]["kap_pdr"]["published_at"], "2026-08-05")
        self.assertEqual(bundle["date_model"]["tefas_price"]["semantic"], SEMANTIC_SOURCE_AS_OF)
        self.assertEqual(bundle["date_model"]["kap_izahname"]["semantic"], SEMANTIC_DOCUMENT_VERSION_DATE)

    def test_iat_ybf_publication_is_2026_02_27(self) -> None:
        iat = dict((load_kap_official_bundle().get("funds") or {}).get("IAT") or {})
        ybf = dict(iat.get("ybf") or {})
        self.assertEqual(ybf["as_of"], "2026-02-27")
        self.assertEqual(ybf["published_at"], "2026-02-27")
        self.assertNotEqual(ybf["as_of"], "2027-02-27")
        self.assertEqual(default_tefas_fund_provider().kap_mandate("IAT").as_of, "2026-02-27")
        bundle = compute_turkiye_fund_snapshots("IAT", calculated_at=CALCULATED_AT)
        self.assertEqual(bundle["source_as_of"]["kap_mandate"], "2026-02-27")
        self.assertNotIn("2027-02-27", str(bundle["source_as_of"]))

    def test_source_as_of_is_not_calculated_at(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            bundle = compute_turkiye_fund_snapshots(code, calculated_at=CALCULATED_AT)
            sources = bundle["source_as_of"]
            self.assertEqual(sources["tefas_price"], "2026-08-28")
            self.assertEqual(sources["kap_pdr"], "2026-07")
            self.assertNotEqual(sources["tefas_price"], CALCULATED_AT)
            self.assertNotEqual(sources["kap_mandate"], CALCULATED_AT)
            self.assertEqual(sources["date_model"]["kap_pdr"]["semantic"], SEMANTIC_REPORT_PERIOD)

    def test_idempotency_after_corrected_provenance(self) -> None:
        current = compute_turkiye_fund_snapshots("IAT", calculated_at=CALCULATED_AT)
        stale = source_as_of_bundle(
            tefas_price="2026-08-28",
            kap_pdr="2026-07",
            kap_mandate="2027-02-27",
            kap_izahname="2022-07-08",
            calculated_at="2027-03-01T00:00:00+00:00",
        )
        self.assertEqual(
            layer_idempotency_dates(LAYER_FUND_INTELLIGENCE, current["source_as_of"]),
            layer_idempotency_dates(LAYER_FUND_INTELLIGENCE, stale),
        )
        self.assertEqual(
            layer_idempotency_dates(LAYER_ECONOMIC_EXPOSURE, current["source_as_of"]),
            layer_idempotency_dates(LAYER_ECONOMIC_EXPOSURE, stale),
        )
        self.assertEqual(
            layer_idempotency_dates(LAYER_EIGHT_E, current["source_as_of"]),
            layer_idempotency_dates(LAYER_EIGHT_E, stale),
        )
        self.assertNotEqual(
            layer_idempotency_dates(LAYER_IDENTITY, current["source_as_of"]),
            layer_idempotency_dates(LAYER_IDENTITY, stale),
        )
        self.assertNotEqual(
            layer_idempotency_dates(LAYER_PARTICIPATION, current["source_as_of"]),
            layer_idempotency_dates(LAYER_PARTICIPATION, stale),
        )
        first = compute_turkiye_fund_snapshots("IAT", calculated_at="2026-08-30T10:00:00+00:00")
        second = compute_turkiye_fund_snapshots("IAT", calculated_at="2026-08-30T22:00:00+00:00")
        self.assertEqual(
            first[LAYER_FUND_INTELLIGENCE].idempotency_key,
            second[LAYER_FUND_INTELLIGENCE].idempotency_key,
        )
        self.assertNotEqual(first[LAYER_FUND_INTELLIGENCE].calculated_at, second[LAYER_FUND_INTELLIGENCE].calculated_at)

    def test_dry_run_preserves_frozen_outputs(self) -> None:
        run = run_turkiye_fund_refresh(calculated_at=CALCULATED_AT)
        self.assertEqual(run.writes, 0)
        self.assertTrue(run.dry_run)
        self.assertNotIn("2027-02-27", str(run.to_dict()))
        for code, (score, state) in FROZEN_FI.items():
            bundle = compute_turkiye_fund_snapshots(code, calculated_at=CALCULATED_AT)
            self.assertEqual(bundle[LAYER_PARTICIPATION].payload["status"], PARTICIPATION_STATUS_UYGUN)
            self.assertEqual(bundle[LAYER_FUND_INTELLIGENCE].payload["overall_score"], score)
            self.assertEqual(bundle[LAYER_FUND_INTELLIGENCE].payload["investment_state"], state)
            self.assertEqual(bundle[LAYER_EIGHT_E].payload["decision"], DECISION_WATCH)
            self.assertFalse(bundle[LAYER_EIGHT_E].payload["increase_allowed"])
            self.assertNotIn("2027-02-27", str(bundle["source_as_of"]))

    def test_regression_isolation(self) -> None:
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        sp = default_official_sp_funds_provider()
        tefas = default_tefas_fund_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertTrue(sp.supports(symbol))
            self.assertFalse(tefas.supports(symbol))
        self.assertEqual(evaluate_pilot_participation("IAT").participation_status, PARTICIPATION_STATUS_UYGUN)
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        self.assertNotIn("allocate_new_money", DATES.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertTrue(callable(allocate_new_money))


if __name__ == "__main__":
    unittest.main()
