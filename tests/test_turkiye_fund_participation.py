from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import evaluate_official_fund_intelligence
from services.fund_product_contract import (
    AUTHORITY_SPK,
    AUTHORITY_TKBB,
    EVIDENCE_TYPE_ICAZET,
    FRAMEWORK_TURKIYE_PARTICIPATION,
    FRESHNESS_STALE,
    GOVERNANCE_CONFIRMED,
    GOVERNANCE_MISSING,
    GOVERNANCE_PARTIAL,
    HOLDINGS_COMPLIANT,
    IDENTITY_RESOLVED,
    MANDATE_CONFIRMED,
    MANDATE_UNRESOLVED,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
    PILOT_FUND_SYMBOLS,
    PILOT_TEFAS_FUND_CODES,
    PURIFICATION_MISSING,
    PURIFICATION_NOT_REQUIRED,
    PURIFICATION_POLICY_ONLY,
)
from services.official_tefas_product import default_tefas_fund_provider
from services.official_turkiye_fund_participation import (
    UYGUN_REQUIREMENTS,
    evaluate_pilot_participation,
    evaluate_turkiye_fund_participation,
    load_participation_bundle,
    mandate_from_name_only,
    mandate_from_umbrella_only,
    theoretical_publishability,
    tkbb_framework,
    turkiye_participation_framework,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
)
from services.wealth_new_money_allocation import allocate_new_money

PARTICIPATION = Path("services/official_turkiye_fund_participation.py")
FRAMEWORK = Path("services/official_turkiye_fund_evidence/turkiye_participation_framework.json")
TEFAS = Path("services/official_tefas_product.py")
BIST = Path("services/bist_refresh_contract.py")
US_SI = Path("services/security_intelligence_engine.py")
EIGHT_E = Path("services/portfolio_security_decision_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
SP_FUNDS = Path("services/official_sp_funds_product.py")

FROZEN_FI = {
    "AIS": (70.39, "WATCH"),
    "ZPE": (66.32, "WATCH"),
    "IAT": (60.49, "NEUTRAL"),
}


class RegulatoryFrameworkTests(unittest.TestCase):
    def test_spk_framework_provenance(self) -> None:
        framework = turkiye_participation_framework()
        self.assertEqual(framework.framework_id, FRAMEWORK_TURKIYE_PARTICIPATION)
        self.assertEqual(framework.authority, AUTHORITY_SPK)
        self.assertEqual(framework.version, "21.11.2024-60/1696")
        self.assertEqual(framework.as_of, "2024-11-21")
        self.assertIn("spk.gov.tr", framework.source_url)
        self.assertTrue(framework.excerpts)
        self.assertIn("spk.gov.tr", framework.provenance)
        tkbb = tkbb_framework()
        self.assertEqual(tkbb.authority, AUTHORITY_TKBB)
        self.assertIn("Danışma Kurulu", tkbb.title)
        source = PARTICIPATION.read_text(encoding="utf-8")
        self.assertNotIn("musaffa", source.lower())
        self.assertNotIn("zoya", source.lower())
        self.assertNotIn("islamicly", source.lower())
        self.assertIn("UYGUN_REQUIREMENTS", source)

    def test_uygun_requirements_are_declared_before_pilots(self) -> None:
        self.assertEqual(
            UYGUN_REQUIREMENTS,
            (
                "valid_deterministic_turkish_fund_identity",
                "applicable_spk_regulatory_framework",
                "explicit_fund_specific_participation_mandate",
                "governance_or_equivalent_approval_confirmed",
                "latest_official_holdings_available",
                "no_material_contradiction",
                "evidence_freshness_acceptable",
            ),
        )
        text = PARTICIPATION.read_text(encoding="utf-8")
        self.assertLess(text.find("UYGUN_REQUIREMENTS"), text.find("def evaluate_turkiye_fund_participation"))


class NameAndUmbrellaIsolationTests(unittest.TestCase):
    def test_fund_name_alone_cannot_produce_uygun(self) -> None:
        self.assertEqual(
            mandate_from_name_only("AK PORTFÖY PARA PİYASASI KATILIM FONU"),
            MANDATE_UNRESOLVED,
        )
        verdict = evaluate_turkiye_fund_participation(
            "AIS",
            identity_status=IDENTITY_RESOLVED,
            official_name="AK PORTFÖY PARA PİYASASI KATILIM FONU",
            name_only=True,
        )
        self.assertEqual(verdict.mandate_state, MANDATE_UNRESOLVED)
        self.assertEqual(verdict.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertFalse(verdict.research_allowed)
        self.assertIn("NAME_ALONE_INSUFFICIENT", verdict.blockers)

    def test_umbrella_type_alone_cannot_produce_uygun(self) -> None:
        self.assertEqual(mandate_from_umbrella_only("Katılım Şemsiye Fonu"), MANDATE_UNRESOLVED)
        verdict = evaluate_turkiye_fund_participation(
            "IAT",
            identity_status=IDENTITY_RESOLVED,
            umbrella_type="KATILIM ŞEMSİYE FONU",
            umbrella_only=True,
        )
        self.assertEqual(verdict.mandate_state, MANDATE_UNRESOLVED)
        self.assertEqual(verdict.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertIn("UMBRELLA_ALONE_INSUFFICIENT", verdict.blockers)


class MandateAndGovernanceTests(unittest.TestCase):
    def test_explicit_fund_mandate(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            verdict = evaluate_pilot_participation(code)
            self.assertEqual(verdict.mandate_state, MANDATE_CONFIRMED)
            self.assertTrue(
                any(item.evidence_type == "MANDATE" and item.fund_code == code for item in verdict.evidence)
            )

    def test_zpe_uygun_does_not_depend_on_katilim_umbrella(self) -> None:
        provider = default_tefas_fund_provider()
        umbrella = provider.kap_mandate("ZPE").umbrella_type or ""
        self.assertIn("Hisse", umbrella)
        self.assertNotIn("Katılım", umbrella)
        verdict = evaluate_pilot_participation("ZPE")
        self.assertEqual(verdict.mandate_state, MANDATE_CONFIRMED)
        self.assertEqual(verdict.participation_status, PARTICIPATION_STATUS_UYGUN)

    def test_governance_confirmed_and_equivalent_approval(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            verdict = evaluate_pilot_participation(code)
            self.assertEqual(verdict.governance_state, GOVERNANCE_CONFIRMED)
            self.assertFalse(verdict.icazet_present)
            self.assertIsNotNone(verdict.equivalent_approval_reason)
            assert verdict.equivalent_approval_reason is not None
            self.assertIn("Danışma", verdict.equivalent_approval_reason)
            self.assertIn("SPK Rehber 1.6", verdict.equivalent_approval_reason)
            self.assertIn("icazet PDF was not located", verdict.equivalent_approval_reason)

    def test_governance_partial_and_missing(self) -> None:
        partial = evaluate_turkiye_fund_participation(
            "AIS",
            identity_status=IDENTITY_RESOLVED,
            forced_governance=GOVERNANCE_PARTIAL,
        )
        self.assertEqual(partial.governance_state, GOVERNANCE_PARTIAL)
        self.assertEqual(partial.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertFalse(partial.research_allowed)
        self.assertIn("GOVERNANCE_NOT_CONFIRMED", partial.blockers)
        missing = evaluate_turkiye_fund_participation(
            "ZPE",
            identity_status=IDENTITY_RESOLVED,
            forced_governance=GOVERNANCE_MISSING,
        )
        self.assertEqual(missing.governance_state, GOVERNANCE_MISSING)
        self.assertEqual(missing.participation_status, PARTICIPATION_STATUS_KONTROL_ET)

    def test_icazet_document_is_stored_separately(self) -> None:
        bundle = load_participation_bundle()
        funds = dict(bundle["funds"])
        ais = dict(funds["AIS"])
        ais["icazet_document_url"] = "https://www.kap.org.tr/tr/api/file/download/official-icazet"
        funds["AIS"] = ais
        verdict = evaluate_turkiye_fund_participation(
            "AIS",
            identity_status=IDENTITY_RESOLVED,
            bundle={**bundle, "funds": funds},
        )
        self.assertTrue(verdict.icazet_present)
        icazet = [item for item in verdict.evidence if item.evidence_type == EVIDENCE_TYPE_ICAZET]
        self.assertEqual(len(icazet), 1)
        self.assertEqual(icazet[0].source_url, ais["icazet_document_url"])
        self.assertTrue(icazet[0].applies_to_fund)


class HoldingsContradictionFreshnessTests(unittest.TestCase):
    def test_holdings_compliance_evidence(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            verdict = evaluate_pilot_participation(code)
            self.assertEqual(verdict.holdings_state, HOLDINGS_COMPLIANT)
            self.assertFalse(verdict.contradiction)
            self.assertTrue(any(item.evidence_type == "HOLDINGS" for item in verdict.evidence))

    def test_contradiction_firewall(self) -> None:
        verdict = evaluate_turkiye_fund_participation(
            "AIS",
            identity_status=IDENTITY_RESOLVED,
            forced_contradiction=("HOLDING_GROUP_OUTSIDE_MANDATE:INTEREST_BEARING",),
        )
        self.assertTrue(verdict.contradiction)
        self.assertEqual(verdict.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertFalse(verdict.research_allowed)
        self.assertIn("MATERIAL_CONTRADICTION", verdict.blockers)
        adverse = evaluate_turkiye_fund_participation(
            "IAT",
            identity_status=IDENTITY_RESOLVED,
            forced_contradiction=("ADVERSE_OFFICIAL_HOLDING",),
        )
        self.assertEqual(adverse.participation_status, PARTICIPATION_STATUS_UYGUN_DEGIL)
        self.assertFalse(adverse.research_allowed)

    def test_stale_evidence_blocks_uygun(self) -> None:
        verdict = evaluate_turkiye_fund_participation(
            "AIS",
            identity_status=IDENTITY_RESOLVED,
            as_of=date(2027, 2, 1),
        )
        self.assertEqual(verdict.freshness, FRESHNESS_STALE)
        self.assertEqual(verdict.participation_status, PARTICIPATION_STATUS_KONTROL_ET)
        self.assertIn("EVIDENCE_STALE", verdict.blockers)
        self.assertFalse(verdict.research_allowed)


class PurificationSeparationTests(unittest.TestCase):
    def test_purification_is_separate_and_factor_is_not_invented(self) -> None:
        ais = evaluate_pilot_participation("AIS")
        zpe = evaluate_pilot_participation("ZPE")
        iat = evaluate_pilot_participation("IAT")
        self.assertEqual(ais.purification_state, PURIFICATION_POLICY_ONLY)
        self.assertTrue(ais.purification_policy_present)
        self.assertEqual(zpe.purification_state, PURIFICATION_MISSING)
        self.assertEqual(iat.purification_state, PURIFICATION_NOT_REQUIRED)
        for verdict in (ais, zpe, iat):
            self.assertIsNone(verdict.purification_factor_pct)
            self.assertNotEqual(verdict.participation_status, PARTICIPATION_STATUS_UYGUN_DEGIL)
        provider = default_tefas_fund_provider()
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertIsNone(provider.purification_evidence(code).latest_factor_pct)


class DeterministicVerdictTests(unittest.TestCase):
    def test_pilot_verdicts_and_research_gate(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            verdict = evaluate_pilot_participation(code)
            self.assertTrue(verdict.identity_resolved)
            self.assertTrue(verdict.framework_applicable)
            self.assertEqual(verdict.mandate_state, MANDATE_CONFIRMED)
            self.assertEqual(verdict.governance_state, GOVERNANCE_CONFIRMED)
            self.assertEqual(verdict.holdings_state, HOLDINGS_COMPLIANT)
            self.assertFalse(verdict.contradiction)
            self.assertEqual(verdict.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(verdict.research_allowed)
            self.assertEqual(verdict.methodology_id, METHODOLOGY_TURKIYE_FUND_PARTICIPATION)
            evidence = default_tefas_fund_provider().sharia_evidence(code)
            self.assertEqual(evidence.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertEqual(evidence.methodology, METHODOLOGY_TURKIYE_FUND_PARTICIPATION)
            self.assertTrue(evidence.official_certificate_listed)
            self.assertIn("NO_INVENTED_UYGUN", evidence.limitations)

    def test_research_allowed_only_when_uygun(self) -> None:
        blocked = evaluate_turkiye_fund_participation(
            "AIS",
            identity_status=IDENTITY_RESOLVED,
            forced_governance=GOVERNANCE_PARTIAL,
        )
        self.assertNotEqual(blocked.participation_status, PARTICIPATION_STATUS_UYGUN)
        self.assertFalse(blocked.research_allowed)

    def test_fi_score_isolation(self) -> None:
        for code, (score, state) in FROZEN_FI.items():
            view = evaluate_official_fund_intelligence(code)
            self.assertEqual(view.score, score)
            self.assertEqual(view.state, state)
            self.assertTrue(view.participation.eligible)
            self.assertTrue(view.publishable)
            generic = view.generic_intelligence()
            self.assertEqual(generic["si_state"], state)
            self.assertEqual(generic["si_score"], score)

    def test_theoretical_publishability_is_not_persisted(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertTrue(theoretical_publishability(code))
        source = PARTICIPATION.read_text(encoding="utf-8")
        self.assertNotIn("supabase", source.lower())
        self.assertNotIn("DATABASE_URL", source)
        self.assertIn("Does not persist a snapshot", source)


class IsolationTests(unittest.TestCase):
    def test_sp_funds_participation_isolation(self) -> None:
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        provider = default_tefas_fund_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertFalse(provider.supports(symbol))
        self.assertNotIn("turkiye_fund_participation", SP_FUNDS.read_text(encoding="utf-8"))

    def test_bist_and_us_equity_isolation(self) -> None:
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        self.assertNotIn("turkiye_fund_participation", US_SI.read_text(encoding="utf-8"))

    def test_eight_e_and_new_money_isolation(self) -> None:
        provider = default_tefas_fund_provider()
        for code in PILOT_TEFAS_FUND_CODES:
            decision = evaluate_official_fund_decision(code)
            self.assertEqual(decision.decision, DECISION_INSUFFICIENT_DATA)
            self.assertFalse(decision.exposure_increase_allowed)
            self.assertIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, decision.blocking_reasons)
            self.assertNotIn("TURKIYE_FUND_8E_NOT_STARTED", decision.reason_codes)
            forced = evaluate_official_fund_decision(code, provider=provider)
            self.assertEqual(forced.decision, DECISION_INSUFFICIENT_DATA)
            self.assertIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, forced.blocking_reasons)
        self.assertNotIn("evaluate_official_fund_decision", TEFAS.read_text(encoding="utf-8"))
        self.assertNotIn("allocate_new_money", TEFAS.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertNotIn("evaluate_official_fund_intelligence", EIGHT_E.read_text(encoding="utf-8"))
        self.assertTrue(callable(allocate_new_money))
        self.assertNotIn("Musaffa", FRAMEWORK.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
