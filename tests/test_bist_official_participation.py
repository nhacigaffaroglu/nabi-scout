from __future__ import annotations

import unittest
from pathlib import Path

from services.bist_katilim_tum_contract import (
    INDEX_BIST_KATILIM_TUM,
    MEMBERSHIP_MEMBER,
    MEMBERSHIP_NOT_LISTED,
    MEMBERSHIP_SOURCE_UNAVAILABLE,
    SOURCE_BORSA_ISTANBUL,
    UNIVERSE_BIST_KATILIM_TUM,
)
from services.bist_katilim_tum_parser import (
    canonicalize_bist_series_code,
    membership_for_symbol,
    parse_bist_katilim_csv,
)
from services.bist_katilim_tum_source import BistKatilimTumSource
from services.bist_official_participation_contract import (
    DECISION_AUTHORITY_BIST_OFFICIAL,
    EVIDENCE_OFFICIAL_ELIGIBILITY,
    PERIOD_COMPARABLE,
    PERIOD_MISMATCH,
    SHADOW_IDENTITY_REJECTED,
)
from services.bist_official_participation_resolver import (
    audit_katilim_universe,
    compare_kafif_to_financial_period,
    resolve_official_bist_participation_evidence,
)
from services.bist_symbol_mapping import canonical_bist_identity
from services.kap_kafif_contract import MAPPING_UNMAPPED
from services.kap_kafif_methodology_map import audit_kafif_to_nabi_mapping
from services.kap_kafif_parser import (
    latest_kafif_discovery,
    parse_kafif_disclosure_index,
    parse_public_kafif_html,
    parse_tr_decimal,
)
from services.kap_kafif_source import KapKafifSource
from services.participation_intelligence_contract import (
    CONFIDENCE_HIGH,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
)
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_master_contract import INSTRUMENT_EQUITY, SOURCE_BIST
from tests.fixtures.bist_katilim_tum_pilot import compact_katilim_csv
from tests.fixtures.kap_kafif_pilot import (
    asels_kafif_html,
    bimas_kafif_html,
    kafif_member_index_html,
    tuprs_kafif_html,
)


RESOLVER = Path("services/bist_official_participation_resolver.py")
KAFIF_PARSER = Path("services/kap_kafif_parser.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")


class BistKatilimTumParserTests(unittest.TestCase):
    def test_series_canonicalization(self) -> None:
        self.assertEqual(canonicalize_bist_series_code("ASELS.E"), "ASELS")
        self.assertEqual(canonicalize_bist_series_code("bimas.e"), "BIMAS")
        self.assertEqual(canonicalize_bist_series_code("TUPRS"), "TUPRS")

    def test_xktum_membership_and_provenance(self) -> None:
        snapshot = parse_bist_katilim_csv(compact_katilim_csv())
        self.assertEqual({member.symbol for member in snapshot.members}, {"ASELS", "BIMAS", "TUPRS"})
        asels = membership_for_symbol(snapshot, "ASELS.E")
        self.assertEqual(asels.status, MEMBERSHIP_MEMBER)
        self.assertTrue(asels.membership)
        self.assertEqual(asels.member.index_code, INDEX_BIST_KATILIM_TUM)
        self.assertEqual(asels.member.universe, UNIVERSE_BIST_KATILIM_TUM)
        self.assertEqual(asels.member.source, SOURCE_BORSA_ISTANBUL)
        self.assertEqual(asels.member.as_of, "2026-08-31")
        self.assertNotIn("XXXXX", {member.symbol for member in snapshot.members})

    def test_non_member_is_not_uygun_degil(self) -> None:
        snapshot = parse_bist_katilim_csv(compact_katilim_csv())
        missing = membership_for_symbol(snapshot, "XXXXX.E")
        self.assertEqual(missing.status, MEMBERSHIP_NOT_LISTED)
        self.assertFalse(missing.membership)
        self.assertIn("not UYGUN_DEGIL", missing.limitation)

    def test_source_unavailable_is_not_negative(self) -> None:
        missing = membership_for_symbol(None, "ASELS", source_unavailable=True)
        self.assertEqual(missing.status, MEMBERSHIP_SOURCE_UNAVAILABLE)
        self.assertIsNone(missing.membership)
        source = BistKatilimTumSource(allow_live=False, cache_dir=Path("/tmp/nabi-katilim-empty"))
        live = source.membership_for("ASELS")
        self.assertEqual(live.status, MEMBERSHIP_SOURCE_UNAVAILABLE)


class KapKafifParserTests(unittest.TestCase):
    def test_metadata_q1_q4_and_official_ratios(self) -> None:
        doc = parse_public_kafif_html(asels_kafif_html(), symbol="ASELS", disclosure_id="1643144")
        self.assertEqual(doc.disclosure_id, "1643144")
        self.assertEqual(doc.financial_year, "2026")
        self.assertEqual(doc.period, "YTD")
        self.assertTrue(doc.consolidated)
        self.assertEqual(doc.presentation_currency, "TRY")
        self.assertFalse(doc.q1_unsuitable_activity)
        self.assertFalse(doc.q2_unsuitable_privilege)
        self.assertFalse(doc.q3_prohibited_support)
        self.assertFalse(doc.q4_direct_non_compliant)
        self.assertEqual(doc.non_compliant_income_ratio, 4.14)
        self.assertEqual(doc.non_compliant_asset_ratio, 12.95)
        self.assertEqual(doc.non_compliant_debt_ratio, 13.9)
        self.assertTrue(doc.complete)

    def test_comma_decimal_and_integer_ratio(self) -> None:
        self.assertEqual(parse_tr_decimal("4,14"), 4.14)
        self.assertEqual(parse_tr_decimal("0"), 0.0)
        tuprs = parse_public_kafif_html(tuprs_kafif_html(), symbol="TUPRS", disclosure_id="1643837")
        self.assertEqual(tuprs.non_compliant_income_ratio, 2.24)
        self.assertEqual(tuprs.non_compliant_asset_ratio, 25.0)
        self.assertEqual(tuprs.non_compliant_debt_ratio, 7.52)

    def test_discovery_prefers_latest(self) -> None:
        rows = parse_kafif_disclosure_index(kafif_member_index_html())
        self.assertEqual({row.disclosure_id for row in rows}, {"1643144", "1561061"})
        latest = latest_kafif_discovery(rows)
        self.assertEqual(latest.disclosure_id, "1643144")

    def test_missing_kafif_fail_closed(self) -> None:
        source = KapKafifSource(allow_live=False, cache_dir=Path("/tmp/nabi-kafif-empty"))
        with self.assertRaises(Exception):
            source.fetch_form("9999999", symbol="ASELS")


class MappingAndResolverTests(unittest.TestCase):
    def test_kafif_mapping_does_not_invent_nabi_gates(self) -> None:
        audits = {item.kafif_field: item for item in audit_kafif_to_nabi_mapping()}
        self.assertEqual(audits["q2_unsuitable_privilege_in_articles"].mapping_status, MAPPING_UNMAPPED)
        self.assertEqual(audits["bist_katilim_tum_membership"].mapping_status, MAPPING_UNMAPPED)
        self.assertNotIn("UYGUN", " ".join(item.note for item in audits.values()))

    def test_official_member_complete_kafif_is_uygun(self) -> None:
        snapshot = parse_bist_katilim_csv(compact_katilim_csv())
        kafif = parse_public_kafif_html(bimas_kafif_html(), symbol="BIMAS", disclosure_id="1651659")
        evidence = resolve_official_bist_participation_evidence(
            symbol="BIMAS",
            identity_source=SOURCE_BIST,
            membership=membership_for_symbol(snapshot, "BIMAS"),
            kafif=kafif,
            financial_period="YTD",
            financial_period_end="2026-06-30",
        )
        self.assertEqual(evidence.official_eligibility, EVIDENCE_OFFICIAL_ELIGIBILITY)
        self.assertTrue(evidence.kafif_evidence_complete)
        self.assertEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(evidence.decision_authority, DECISION_AUTHORITY_BIST_OFFICIAL)
        self.assertEqual(evidence.confidence, CONFIDENCE_HIGH)
        self.assertEqual(evidence.period_vs_financial_report, PERIOD_COMPARABLE)
        self.assertFalse(evidence.persisted)

    def test_missing_kafif_and_unavailable_source_fail_closed(self) -> None:
        missing = resolve_official_bist_participation_evidence(
            symbol="ASELS",
            identity_source=SOURCE_BIST,
            membership=membership_for_symbol(None, "ASELS", source_unavailable=True),
            kafif=None,
        )
        self.assertEqual(missing.nabi_participation_shadow, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertFalse(missing.kafif_evidence_complete)

    def test_period_mismatch(self) -> None:
        kafif = parse_public_kafif_html(asels_kafif_html(), symbol="ASELS", disclosure_id="1643144")
        self.assertEqual(
            compare_kafif_to_financial_period(kafif, financial_period="FY", financial_period_end="2025-12-31"),
            PERIOD_MISMATCH,
        )

    def test_us_isolation(self) -> None:
        snapshot = parse_bist_katilim_csv(compact_katilim_csv())
        kafif = parse_public_kafif_html(asels_kafif_html(), symbol="AAPL", disclosure_id="1643144")
        for symbol in ("AAPL", "CRM"):
            evidence = resolve_official_bist_participation_evidence(
                symbol=symbol,
                identity_source="sec_company_facts",
                membership=membership_for_symbol(snapshot, symbol),
                kafif=kafif,
            )
            self.assertEqual(evidence.nabi_participation_shadow, SHADOW_IDENTITY_REJECTED)
            self.assertIsNone(canonical_bist_identity(symbol))

    def test_universe_audit_does_not_expand_production(self) -> None:
        snapshot = parse_bist_katilim_csv(compact_katilim_csv())
        audit = audit_katilim_universe(snapshot, ("ASELS", "BIMAS"))
        self.assertEqual(audit.member_count, 3)
        self.assertEqual(audit.matched_security_master, ("ASELS", "BIMAS"))
        self.assertEqual(audit.unmatched_symbols, ("TUPRS",))

    def test_no_participation_persistence_and_8e_unchanged(self) -> None:
        text = RESOLVER.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_financial_rules", text)
        self.assertNotIn("assessment_repository", text)
        self.assertNotIn("Rafinaj", KAFIF_PARSER.read_text(encoding="utf-8"))
        result = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="ASELS",
                participation_status=PARTICIPATION_STATUS_UYGUN,
                research_allowed=True,
                si_state=STATE_ATTRACTIVE,
                instrument_type=INSTRUMENT_EQUITY,
                market="TR",
            )
        )
        self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
        self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
        self.assertNotIn("8e_enabled", ENGINE.read_text(encoding="utf-8"))
