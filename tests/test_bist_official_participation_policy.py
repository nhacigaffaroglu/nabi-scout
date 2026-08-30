from __future__ import annotations

import unittest
from pathlib import Path

from services.bist_katilim_tum_parser import membership_for_symbol, parse_bist_katilim_csv
from services.bist_official_participation_contract import (
    BASIS_KAFIF_INCOMPLETE,
    BASIS_KAFIF_MISSING,
    BASIS_NOT_LISTED_NOT_NEGATIVE,
    BASIS_SOURCE_UNAVAILABLE,
    DECISION_AUTHORITY_BIST_OFFICIAL,
    FRESHNESS_POLICY_NEEDS_FOLLOWUP,
    METHODOLOGY_NEGATIVE_MAPPING_UNRESOLVED,
    NAMESPACE_BIST_OFFICIAL,
    NAMESPACE_MSCI,
    SHADOW_IDENTITY_REJECTED,
)
from services.bist_official_participation_policy import (
    apply_bist_official_participation_policy,
    audit_kafif_negative_failure_semantics,
    build_bist_official_assessment,
    official_decision_compare_key,
    resolve_canonical_bist_official_participation,
)
from services.bist_official_participation_resolver import (
    resolve_official_bist_participation_evidence,
)
from services.kap_kafif_parser import parse_public_kafif_html
from services.participation_assessment_service import assess_equity_participation
from services.participation_intelligence_contract import (
    CONFIDENCE_HIGH,
    PARTICIPATION_SOURCE_BIST_OFFICIAL,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
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
    compact_kafif_html,
    tuprs_kafif_html,
)

POLICY = Path("services/bist_official_participation_policy.py")
ASSESSMENT = Path("services/participation_assessment_service.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
SI_FIREWALL = Path("services/security_intelligence_firewall.py")


def _snapshot():
    return parse_bist_katilim_csv(compact_katilim_csv())


def _kafif(symbol: str, html: str, disclosure_id: str):
    return parse_public_kafif_html(html, symbol=symbol, disclosure_id=disclosure_id)


def _resolve(symbol: str, html: str, disclosure_id: str, **kwargs):
    return resolve_official_bist_participation_evidence(
        symbol=symbol,
        identity_source=SOURCE_BIST,
        membership=membership_for_symbol(_snapshot(), symbol),
        kafif=_kafif(symbol, html, disclosure_id),
        **kwargs,
    )


class NegativeKafifMappingTests(unittest.TestCase):
    def test_no_automatic_uygun_degil_from_kafif_fields(self) -> None:
        audit = audit_kafif_negative_failure_semantics()
        self.assertFalse(audit.automatic_uygun_degil_implemented)
        self.assertTrue(audit.methodology_negative_mapping_unresolved)
        self.assertEqual(audit.explicit_safe_failure_fields, ())
        self.assertIn("q1_unsuitable_activity", audit.unresolved_fields)
        self.assertIn("q3_prohibited_support", audit.unresolved_fields)
        self.assertFalse(any(item.safe_for_automatic_uygun_degil for item in audit.fields))
        q3 = next(item for item in audit.fields if item.kafif_field == "q3_prohibited_support")
        self.assertIn("differ", q3.note.lower())

    def test_q1_evet_is_not_uygun_degil(self) -> None:
        html = compact_kafif_html(symbol="ASELS", q1="EVET")
        evidence = _resolve("ASELS", html, "1643144")
        self.assertNotEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_UYGUN_DEGIL)
        self.assertEqual(evidence.negative_mapping, METHODOLOGY_NEGATIVE_MAPPING_UNRESOLVED)
        self.assertEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_UYGUN)


class PositivePolicyTests(unittest.TestCase):
    def test_member_complete_current_kafif_is_uygun(self) -> None:
        for symbol, html, disclosure_id in (
            ("ASELS", asels_kafif_html(), "1643144"),
            ("BIMAS", bimas_kafif_html(), "1651659"),
            ("TUPRS", tuprs_kafif_html(), "1643837"),
        ):
            evidence = _resolve(
                symbol,
                html,
                disclosure_id,
                financial_period="YTD",
                financial_period_end="2026-06-30",
            )
            self.assertEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_UYGUN)
            self.assertEqual(evidence.decision_authority, DECISION_AUTHORITY_BIST_OFFICIAL)
            self.assertEqual(evidence.confidence, CONFIDENCE_HIGH)
            self.assertIn("BIST Katılım Tüm", evidence.explanation)
            self.assertIn("KAFİF", evidence.explanation)
            self.assertNotIn("MSCI", evidence.explanation)
            self.assertFalse(evidence.persisted)

    def test_canonical_assessment_reuses_status_vocabulary(self) -> None:
        evidence = _resolve("BIMAS", bimas_kafif_html(), "1651659")
        assessment = build_bist_official_assessment(evidence)
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(assessment.source, PARTICIPATION_SOURCE_BIST_OFFICIAL)
        self.assertEqual(assessment.confidence, CONFIDENCE_HIGH)
        self.assertTrue(assessment.is_bist_official())
        self.assertEqual(assessment.evidence["namespace"], NAMESPACE_BIST_OFFICIAL)
        self.assertNotEqual(assessment.evidence["namespace"], NAMESPACE_MSCI)
        self.assertEqual(assessment.evidence["source_notification_id"], "1651659")
        self.assertEqual(assessment.evidence["source_membership_state"], "MEMBER")
        self.assertTrue(assessment.evidence["source_period"])
        self.assertEqual(assessment.freshness_label, FRESHNESS_POLICY_NEEDS_FOLLOWUP)


class AmbiguousPolicyTests(unittest.TestCase):
    def test_member_missing_kafif_is_kontrol_et(self) -> None:
        evidence = resolve_official_bist_participation_evidence(
            symbol="ASELS",
            identity_source=SOURCE_BIST,
            membership=membership_for_symbol(_snapshot(), "ASELS"),
            kafif=None,
        )
        self.assertEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(evidence.decision_basis, BASIS_KAFIF_MISSING)
        self.assertNotEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_member_incomplete_kafif_is_kontrol_et(self) -> None:
        html = (
            "<html><body><div>Katılım Finansı İlkeleri Bilgi Formu</div>"
            '<table class="tbl_KFIF-General-Info-Form">'
            "<tr><td>esas sözleşmesinde yer alan faaliyet alanları</td>"
            "<td>HAYIR</td></tr></table></body></html>"
        )
        evidence = _resolve("ASELS", html, "1643144")
        self.assertFalse(evidence.kafif_evidence_complete)
        self.assertEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(evidence.decision_basis, BASIS_KAFIF_INCOMPLETE)

    def test_not_listed_alone_is_kontrol_et(self) -> None:
        evidence = resolve_official_bist_participation_evidence(
            symbol="XXXXX",
            identity_source=SOURCE_BIST,
            membership=membership_for_symbol(_snapshot(), "XXXXX"),
            kafif=None,
        )
        self.assertEqual(evidence.membership.status, "NOT_LISTED")
        self.assertEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(evidence.decision_basis, BASIS_NOT_LISTED_NOT_NEGATIVE)
        self.assertNotEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_UYGUN_DEGIL)

    def test_source_unavailable_is_kontrol_et(self) -> None:
        evidence = resolve_official_bist_participation_evidence(
            symbol="ASELS",
            identity_source=SOURCE_BIST,
            membership=membership_for_symbol(None, "ASELS", source_unavailable=True),
            kafif=None,
        )
        self.assertEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(evidence.decision_basis, BASIS_SOURCE_UNAVAILABLE)

    def test_stale_kafif_period_is_kontrol_et(self) -> None:
        evidence = _resolve(
            "ASELS",
            asels_kafif_html(),
            "1643144",
            financial_period="FY",
            financial_period_end="2025-12-31",
        )
        self.assertEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertEqual(evidence.decision_basis, "KAFIF_PERIOD_NOT_APPLICABLE")

    def test_identity_mismatch_has_no_positive_decision(self) -> None:
        evidence = resolve_official_bist_participation_evidence(
            symbol="AAPL",
            identity_source="sec_company_facts",
            membership=membership_for_symbol(_snapshot(), "AAPL"),
            kafif=_kafif("AAPL", asels_kafif_html(), "1643144"),
        )
        self.assertEqual(evidence.nabi_participation_shadow, SHADOW_IDENTITY_REJECTED)
        self.assertNotEqual(evidence.nabi_participation_shadow, PARTICIPATION_STATUS_UYGUN)
        self.assertNotEqual(evidence.decision_authority, DECISION_AUTHORITY_BIST_OFFICIAL)
        self.assertIsNone(
            resolve_canonical_bist_official_participation(
                symbol="AAPL",
                identity_source="sec_company_facts",
                membership=membership_for_symbol(_snapshot(), "AAPL"),
                kafif=_kafif("AAPL", asels_kafif_html(), "1643144"),
            )
        )


class CanonicalIntegrationTests(unittest.TestCase):
    def test_bist_positive_path_does_not_require_msci(self) -> None:
        result = assess_equity_participation(
            "TUPRS",
            identity_source=SOURCE_BIST,
            official_bist_membership=membership_for_symbol(_snapshot(), "TUPRS"),
            official_bist_kafif=_kafif("TUPRS", tuprs_kafif_html(), "1643837"),
        )
        assessment = result.participation_assessment
        self.assertEqual(assessment.status, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(assessment.source, PARTICIPATION_SOURCE_BIST_OFFICIAL)
        self.assertIsNone(result.financial_screen_result)
        self.assertIsNone(result.financial_inputs)
        self.assertFalse(result.sec_available)
        self.assertTrue(assessment.evidence["msci_fields_not_required"])

    def test_bist_evidence_never_mutates_msci_fields(self) -> None:
        kafif = _kafif("ASELS", asels_kafif_html(), "1643144")
        before = kafif.to_dict()
        resolve_official_bist_participation_evidence(
            symbol="ASELS",
            identity_source=SOURCE_BIST,
            membership=membership_for_symbol(_snapshot(), "ASELS"),
            kafif=kafif,
        )
        after = kafif.to_dict()
        self.assertEqual(before, after)
        self.assertFalse(any(key.startswith("msci.") for key in after))
        self.assertNotIn("evaluate_financial_rules", POLICY.read_text(encoding="utf-8"))

    def test_generic_symbol_member_complete_kafif(self) -> None:
        csv = compact_katilim_csv().replace(
            "XXXXX.E;NOT A PILOT;XK100;BIST KATILIM 100;BIST PARTICIPATION 100;31/08/2026",
            "GENRL.E;GENERIC CO;XKTUM;BIST KATILIM TUM;BIST PARTICIPATION ALL;31/08/2026",
        )
        snapshot = parse_bist_katilim_csv(csv)
        kafif = parse_public_kafif_html(
            compact_kafif_html(symbol="GENRL", issuer="GENERIC A.Ş."),
            symbol="GENRL",
            disclosure_id="1999999",
        )
        result = resolve_canonical_bist_official_participation(
            symbol="GENRL.E",
            identity_source=SOURCE_BIST,
            membership=membership_for_symbol(snapshot, "GENRL.E"),
            kafif=kafif,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.participation_assessment.status, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(result.symbol, "GENRL")
        self.assertEqual(result.participation_assessment.evidence["source_notification_id"], "1999999")

    def test_provenance_and_watcher_key(self) -> None:
        evidence = _resolve("ASELS", asels_kafif_html(), "1643144")
        key = official_decision_compare_key(evidence)
        self.assertEqual(key["symbol"], "ASELS")
        self.assertEqual(key["status"], PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(key["decision_authority"], DECISION_AUTHORITY_BIST_OFFICIAL)
        self.assertEqual(key["source_notification_id"], "1643144")
        self.assertEqual(key["source_membership_state"], "MEMBER")
        self.assertEqual(key["membership_as_of"], "2026-08-31")
        self.assertTrue(key["source_period"])

    def test_fail_closed_ambiguity(self) -> None:
        decided = apply_bist_official_participation_policy(
            resolve_official_bist_participation_evidence(
                symbol="ASELS",
                identity_source=SOURCE_BIST,
                membership=None,
                kafif=None,
            )
        )
        self.assertEqual(decided.nabi_participation_shadow, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertNotEqual(decided.nabi_participation_shadow, PARTICIPATION_STATUS_UYGUN)


class IsolationAndSafetyTests(unittest.TestCase):
    def test_us_aapl_behavior_unchanged_when_bist_evidence_passed(self) -> None:
        snapshot = _snapshot()
        kafif = _kafif("AAPL", asels_kafif_html(), "1643144")
        baseline = assess_equity_participation("AAPL")
        with_official = assess_equity_participation(
            "AAPL",
            official_bist_membership=membership_for_symbol(snapshot, "AAPL"),
            official_bist_kafif=kafif,
        )
        self.assertEqual(
            baseline.participation_assessment.status,
            with_official.participation_assessment.status,
        )
        self.assertEqual(
            baseline.participation_assessment.source,
            with_official.participation_assessment.source,
        )
        self.assertNotEqual(
            with_official.participation_assessment.source,
            PARTICIPATION_SOURCE_BIST_OFFICIAL,
        )

    def test_us_crm_behavior_unchanged_when_bist_evidence_passed(self) -> None:
        baseline = assess_equity_participation("CRM")
        with_official = assess_equity_participation(
            "CRM",
            official_bist_membership=membership_for_symbol(_snapshot(), "CRM"),
            official_bist_kafif=_kafif("CRM", bimas_kafif_html(), "1651659"),
        )
        self.assertEqual(
            baseline.participation_assessment.to_dict(),
            with_official.participation_assessment.to_dict(),
        )

    def test_no_production_writes_and_no_downstream_lift(self) -> None:
        text = POLICY.read_text(encoding="utf-8")
        self.assertNotIn("save_participation_assessment", text)
        self.assertNotIn("append_snapshot", text)
        self.assertNotIn("assessment_repository", ASSESSMENT.read_text(encoding="utf-8"))
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
        if SI_FIREWALL.exists():
            self.assertNotIn("BIST_SI_ENABLED", SI_FIREWALL.read_text(encoding="utf-8"))

    def test_canonical_result_is_not_persisted(self) -> None:
        result = resolve_canonical_bist_official_participation(
            symbol="ASELS",
            identity_source=SOURCE_BIST,
            membership=membership_for_symbol(_snapshot(), "ASELS"),
            kafif=_kafif("ASELS", asels_kafif_html(), "1643144"),
        )
        self.assertFalse(result.participation_assessment.evidence["persisted"])
        self.assertNotIn("evaluate_financial_rules", POLICY.read_text(encoding="utf-8"))
