from __future__ import annotations

import unittest
from pathlib import Path

from services.bist_business_bridge import (
    FINAL_PARTICIPATION_DISABLED,
    BistBusinessIdentityError,
    build_bist_business_bundle,
    business_evidence_from_bist,
    combine_bist_participation_readiness,
)
from services.bist_business_contract import (
    CATEGORY_UNKNOWN,
    READINESS_COMPLETE,
    READINESS_NONE,
    READINESS_PARTIAL,
)
from services.bist_business_normalization import (
    SHARE_CURRENCY_MISMATCH,
    SHARE_MISSING_TOTAL,
    SHARE_PERIOD_MISMATCH,
    SHARE_ZERO_DENOMINATOR,
    map_business_code,
)
from services.kap_financial_bridge import participation_inputs_from_kap, build_kap_normalized_bundle
from services.participation_business_contract import BusinessActivityEvidence
from services.participation_business_engine import evaluate_business_activity
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_master_contract import INSTRUMENT_EQUITY, RESOLUTION_RESOLVED, SOURCE_BIST
from services.security_master_service import SecurityMasterService
from tests.fixtures.bist_business_pilot import (
    FIXTURE_DISCLAIMER,
    PILOT_FIXTURES,
    asels_complete_mapped,
    currency_mismatch_bimas,
    missing_total_revenue_asels,
    tuprs_period_mismatch,
)
from tests.fixtures.kap_financial_pilot import PILOT_RAW_LINES


BRIDGE = Path("services/bist_business_bridge.py")
NORM = Path("services/bist_business_normalization.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
TAXONOMY = Path("config/participation_segment_classification.json")
RULES = Path("config/participation_business_rules.json")


def _bundle(symbol: str):
    segments, totals = PILOT_FIXTURES[symbol]()
    return build_bist_business_bundle(symbol, segments, totals)


class MappingAndShareTests(unittest.TestCase):
    def test_explicit_code_only(self) -> None:
        self.assertEqual(map_business_code("NABI_TEST.BIZ.ELECTRONICS"), "technology")
        self.assertIsNone(map_business_code("NABI_TEST.BIZ.UNLISTED"))
        self.assertIsNone(map_business_code(""))
        self.assertIsNone(map_business_code(None))

    def test_name_is_not_classified(self) -> None:
        from services.bist_business_contract import BistRawBusinessSegment

        _, totals = asels_complete_mapped()
        raw = BistRawBusinessSegment(
            symbol="ASELS",
            segment_name="Casino Gambling Alcohol Bank",
            currency="TRY",
            period="FY",
            source="NABI_TEST_BIST_BUSINESS",
            segment_code=None,
            revenue=10.0,
        )
        bundle = build_bist_business_bundle("ASELS", (raw,), totals)
        self.assertEqual(bundle.segments[0].canonical_category, CATEGORY_UNKNOWN)

    def test_complete_share_derivation(self) -> None:
        bundle = _bundle("ASELS")
        self.assertEqual(bundle.readiness, READINESS_COMPLETE)
        shares = {item.segment_code: item.revenue_share for item in bundle.segments}
        self.assertAlmostEqual(shares["NABI_TEST.BIZ.ELECTRONICS"], 80.0)
        self.assertAlmostEqual(shares["NABI_TEST.BIZ.SERVICES"], 20.0)
        self.assertIsNone(bundle.unknown_share)

    def test_unknown_weight_preserved(self) -> None:
        bundle = _bundle("BIMAS")
        self.assertEqual(bundle.readiness, READINESS_PARTIAL)
        unknown = next(item for item in bundle.segments if item.canonical_category == CATEGORY_UNKNOWN)
        self.assertAlmostEqual(unknown.revenue, 30.0)
        self.assertAlmostEqual(unknown.revenue_share, 30.0)
        self.assertAlmostEqual(bundle.unknown_revenue, 30.0)
        self.assertAlmostEqual(bundle.unknown_share, 30.0)
        self.assertAlmostEqual(bundle.mapped_share, 70.0)

    def test_missing_total_share_null(self) -> None:
        segments, totals = missing_total_revenue_asels()
        bundle = build_bist_business_bundle("ASELS", segments, totals)
        self.assertTrue(all(item.revenue_share is None for item in bundle.segments))
        self.assertEqual(bundle.segments[0].share_limitation, SHARE_MISSING_TOTAL)
        self.assertEqual(bundle.readiness, READINESS_PARTIAL)

    def test_period_and_currency_mismatch(self) -> None:
        period_bundle = build_bist_business_bundle("TUPRS", *tuprs_period_mismatch())
        self.assertEqual(period_bundle.segments[0].share_limitation, SHARE_PERIOD_MISMATCH)
        self.assertTrue(all(item.revenue_share is None for item in period_bundle.segments))
        currency_bundle = build_bist_business_bundle("BIMAS", *currency_mismatch_bimas())
        self.assertEqual(currency_bundle.segments[0].share_limitation, SHARE_CURRENCY_MISMATCH)

    def test_zero_denominator_share_null(self) -> None:
        from services.bist_business_contract import BistRawBusinessTotals

        segments, _ = asels_complete_mapped()
        totals = BistRawBusinessTotals(
            symbol="ASELS",
            currency="TRY",
            period="FY",
            source="NABI_TEST_BIST_BUSINESS",
            total_revenue=0.0,
        )
        bundle = build_bist_business_bundle("ASELS", segments, totals)
        self.assertTrue(all(item.revenue_share is None for item in bundle.segments))
        self.assertEqual(bundle.segments[0].share_limitation, SHARE_ZERO_DENOMINATOR)

    def test_provenance_and_no_verdict_fields(self) -> None:
        bundle = _bundle("ASELS")
        item = bundle.segments[0]
        self.assertEqual(item.source, "NABI_TEST_BIST_BUSINESS")
        self.assertTrue(item.source_document_id)
        self.assertTrue(item.as_of)
        self.assertEqual(item.period, "FY")
        self.assertEqual(item.mapping_rule, "EXPLICIT_CODE_MAP")
        self.assertTrue(item.provenance.get("fixture"))
        payload = bundle.to_dict()
        self.assertNotIn("verdict", payload)
        self.assertNotIn("Uygun", str(payload))
        contract = Path("services/bist_business_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("Uygun", contract)
        self.assertNotIn("evaluate_business_activity", contract)


class BridgeAndReadinessTests(unittest.TestCase):
    def test_business_input_bridge(self) -> None:
        evidence = business_evidence_from_bist(_bundle("ASELS"))
        self.assertEqual(evidence.symbol, "ASELS")
        self.assertEqual(len(evidence.revenue_segments), 2)
        self.assertIsNone(evidence.sector)
        self.assertIsNone(evidence.industry)
        self.assertIsNone(evidence.business_description)
        self.assertEqual(evidence.reported_total_revenue, 100.0)
        self.assertTrue(evidence.source)
        self.assertTrue(evidence.evidence_refs)

    def test_partial_and_missing_evidence(self) -> None:
        mixed = business_evidence_from_bist(_bundle("BIMAS"))
        self.assertTrue(any(item.category == CATEGORY_UNKNOWN for item in mixed.revenue_segments))
        mismatch = business_evidence_from_bist(_bundle("TUPRS"))
        self.assertIsNone(mismatch.reported_total_revenue)
        self.assertTrue(all(item.revenue_pct is None for item in mismatch.revenue_segments))
        empty = build_bist_business_bundle("ASELS", (), None)
        self.assertEqual(empty.readiness, READINESS_NONE)
        self.assertEqual(business_evidence_from_bist(empty).revenue_segments, ())

    def test_no_final_verdict_or_persistence(self) -> None:
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_business_activity", source)
        self.assertNotIn("evaluate_financial_rules", source)
        self.assertNotIn("Uygun", source)
        self.assertNotIn("ParticipationAssessmentRepository", source)
        financial = participation_inputs_from_kap(
            build_kap_normalized_bundle("ASELS", PILOT_RAW_LINES["ASELS"]())
        )[0]
        ready = combine_bist_participation_readiness(
            symbol="ASELS",
            identity_source=SOURCE_BIST,
            financial_inputs=financial,
            business_bundle=_bundle("ASELS"),
        )
        self.assertEqual(ready.financial_input_readiness, READINESS_PARTIAL)
        self.assertEqual(ready.business_input_readiness, READINESS_COMPLETE)
        self.assertFalse(ready.final_participation_ready)
        self.assertEqual(ready.limitation, FINAL_PARTICIPATION_DISABLED)

    def test_financial_and_business_are_independent(self) -> None:
        business_only = combine_bist_participation_readiness(
            symbol="BIMAS",
            identity_source=SOURCE_BIST,
            business_bundle=_bundle("BIMAS"),
        )
        self.assertEqual(business_only.financial_input_readiness, READINESS_NONE)
        self.assertEqual(business_only.business_input_readiness, READINESS_PARTIAL)
        self.assertFalse(business_only.final_participation_ready)


class IsolationAndRegressionTests(unittest.TestCase):
    def test_us_isolation(self) -> None:
        with self.assertRaises(BistBusinessIdentityError):
            build_bist_business_bundle("AAPL", *asels_complete_mapped())
        with self.assertRaises(BistBusinessIdentityError):
            build_bist_business_bundle("CRM", *asels_complete_mapped())
        master = SecurityMasterService()
        self.assertNotEqual(master.resolve_security("AAPL").source, SOURCE_BIST)
        self.assertNotEqual(master.resolve_security("CRM").source, SOURCE_BIST)
        us = evaluate_business_activity(
            "msci_islamic_index_series",
            BusinessActivityEvidence(symbol="AAPL", industry="Gambling"),
        )
        self.assertEqual(us.overall_outcome, "FAIL")

    def test_taxonomy_and_thresholds_unchanged(self) -> None:
        self.assertIn("non_permissible_patterns", TAXONOMY.read_text(encoding="utf-8"))
        self.assertIn("msci_islamic_index_series", RULES.read_text(encoding="utf-8"))
        self.assertNotIn("NABI_TEST.BIZ", RULES.read_text(encoding="utf-8"))
        self.assertNotIn("evaluate_business_activity", NORM.read_text(encoding="utf-8"))

    def test_identity_and_8e(self) -> None:
        master = SecurityMasterService()
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            resolution = master.resolve_security(symbol)
            self.assertEqual(resolution.status, RESOLUTION_RESOLVED)
            self.assertEqual(resolution.source, SOURCE_BIST)
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    si_state=STATE_ATTRACTIVE,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
            self.assertIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, result.blocking_reasons)
        self.assertIn("supports_portfolio_decision", ENGINE.read_text(encoding="utf-8"))
        self.assertNotIn("if symbol in BIST_PORTFOLIO_SYMBOLS", ENGINE.read_text(encoding="utf-8"))

    def test_fixtures_are_synthetic(self) -> None:
        self.assertIn("TEST-ONLY", FIXTURE_DISCLAIMER)
        self.assertIn("Not real", FIXTURE_DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
