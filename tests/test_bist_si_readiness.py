from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from services.bist_si_readiness import (
    EVAL_INSUFFICIENT,
    EVAL_UNSAFE,
    SI_EVALUATION_BLOCKED_BY_READINESS,
    STATUS_BLOCKED,
    audit_bist_si_readiness,
    classify_shadow_evaluation,
    inventory_kap_si_fields,
    kap_payload_is_si_eligible,
)
from services.kap_financial_bridge import kap_security_facts_payload
from services.kap_public_bridge import ingest_public_kap_financials
from services.kap_public_parser import parse_public_kap_html
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_SI_MISSING,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import STATUS_INSUFFICIENT_DATA
from services.security_intelligence_service import SecurityIntelligenceService
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.kap_public_pilot import compact_public_html


POLICY = Path("services/bist_si_readiness.py")
ENGINE = Path("services/portfolio_security_decision_engine.py")
PILOTS = ("ASELS", "BIMAS", "TUPRS")


def _ytd_bundle(symbol: str):
    doc = parse_public_kap_html(
        compact_public_html(),
        symbol=symbol,
        disclosure_id="1",
        source_url="https://www.kap.org.tr/tr/Bildirim/1",
    )
    return ingest_public_kap_financials(doc, symbol=symbol)


class KapPeriodGateTests(unittest.TestCase):
    def test_ytd_payload_is_not_si_eligible(self) -> None:
        bundle = _ytd_bundle("ASELS")
        payload = kap_security_facts_payload(bundle)
        self.assertFalse(kap_payload_is_si_eligible(payload))
        self.assertIsNone(payload.get("revenue"))
        self.assertEqual(payload.get("period_kind"), "FY")

    def test_ytd_inventory_has_no_fy(self) -> None:
        inventory = inventory_kap_si_fields(_ytd_bundle("BIMAS"))
        self.assertEqual(inventory["fy"], "NOT_AVAILABLE")
        self.assertEqual(inventory["ttm"], "NOT_AVAILABLE")
        self.assertEqual(inventory["roic"], "NOT_AVAILABLE")
        self.assertEqual(inventory["total_debt"], "NOT_AVAILABLE")
        self.assertEqual(inventory["shares_outstanding"], "NOT_AVAILABLE")
        self.assertEqual(inventory["revenue"], "AVAILABLE_CANONICAL")


class SecurityFactsBuildTests(unittest.TestCase):
    def test_default_build_has_identity_and_no_financials(self) -> None:
        for symbol in PILOTS:
            facts = SecurityFactsService().build(symbol, allow_sec_cache_replay=False)
            self.assertEqual(facts.symbol, symbol)
            self.assertEqual(facts.currency, "TRY")
            self.assertIsNone(facts.revenue)
            self.assertIsNone(facts.roe)
            self.assertIsNone(facts.market_cap)
            self.assertLess(facts.completeness_pct or 0, 20)

    def test_ytd_bundle_does_not_populate_si_facts(self) -> None:
        facts = SecurityFactsService().build(
            "TUPRS",
            kap_financials=_ytd_bundle("TUPRS"),
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(facts.revenue)
        self.assertIsNone(facts.net_income)
        self.assertIsNone(facts.current_ratio)


class ShadowEvaluationTests(unittest.TestCase):
    def test_empty_facts_are_insufficient_not_attractive(self) -> None:
        si = SecurityIntelligenceService()
        for symbol in PILOTS:
            facts = SecurityFactsService().build(symbol, allow_sec_cache_replay=False)
            view = si.evaluate(facts)
            self.assertEqual(view.overall_status, STATUS_INSUFFICIENT_DATA)
            self.assertIsNone(view.overall_score)
            self.assertFalse(view.investable)
            self.assertEqual(classify_shadow_evaluation(facts), EVAL_INSUFFICIENT)
            audit = audit_bist_si_readiness(facts, kap_bundle=_ytd_bundle(symbol))
            self.assertEqual(audit.readiness_block, SI_EVALUATION_BLOCKED_BY_READINESS)
            self.assertEqual(audit.shadow_evaluation, EVAL_INSUFFICIENT)
            self.assertFalse(audit.persisted)
            for dimension, status in audit.dimensions.items():
                self.assertEqual(status, STATUS_BLOCKED, dimension)

    def test_ytd_period_on_facts_is_unsafe(self) -> None:
        facts = SecurityFactsService().build("ASELS", allow_sec_cache_replay=False)
        tainted = replace(facts, period_kind="YTD", revenue=1.0)
        self.assertEqual(classify_shadow_evaluation(tainted), EVAL_UNSAFE)


class DownstreamSafetyTests(unittest.TestCase):
    def test_8e_and_si_remain_disabled(self) -> None:
        text = POLICY.read_text(encoding="utf-8")
        self.assertNotIn("8e_enabled", text)
        self.assertNotIn("append_snapshot", text)
        self.assertIn(SI_EVALUATION_BLOCKED_BY_READINESS, text)
        for symbol in PILOTS:
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
            self.assertIn(REASON_SI_MISSING, result.blocking_reasons)
        self.assertNotIn("8e_enabled", ENGINE.read_text(encoding="utf-8"))

    def test_us_symbols_do_not_use_kap_readiness(self) -> None:
        aapl = SecurityFactsService().build("AAPL", allow_sec_cache_replay=False)
        self.assertNotEqual(aapl.currency, "TRY")
        crm = SecurityFactsService().build("CRM", allow_sec_cache_replay=False)
        self.assertNotEqual(crm.symbol, "BIMAS")
