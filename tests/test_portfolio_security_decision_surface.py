from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.nabi_intelligence_facade import get_investment_intelligence
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityDecision,
)
from services.portfolio_security_decision_service import (
    evaluate_portfolio_security_for_symbol,
    fail_closed_portfolio_security_decision,
)
from services.research_workflow_service import DEFAULT_RESEARCH_STATUS


PAGE = Path("pages/4_Company_Report.py")
FACADE = Path("services/nabi_intelligence_facade.py")
SERVICE = Path("services/portfolio_security_decision_service.py")
UI = Path("components/portfolio_security_decision_ui.py")
ADVISER = Path("services/wealth_adviser_service.py")


class PortfolioSecurityDecisionSurfaceTests(unittest.TestCase):
    def test_surfaces_use_the_same_8e_entry(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        facade = FACADE.read_text(encoding="utf-8")
        service = SERVICE.read_text(encoding="utf-8")
        ui = UI.read_text(encoding="utf-8")
        self.assertIn("evaluate_portfolio_security_for_symbol", page)
        self.assertIn("render_portfolio_security_decision_section", page)
        self.assertIn("evaluate_portfolio_security_for_symbol", facade)
        self.assertIn("portfolio_security_decision", facade)
        self.assertIn("build_portfolio_security_context", service)
        self.assertIn("evaluate_portfolio_security_decision", service)
        self.assertNotIn("evaluate_security_intelligence", service)
        self.assertNotIn("get_investment_intelligence", service)
        self.assertNotIn("BUY", ui)
        self.assertNotIn("SELL", ui)
        self.assertNotIn("allocated_amount", ui)
        adviser = ADVISER.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_portfolio_security_for_symbol", adviser)

    def test_missing_context_is_insufficient_data(self) -> None:
        result = fail_closed_portfolio_security_decision("CRM")
        self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(result.exposure_increase_allowed)
        empty_client = evaluate_portfolio_security_for_symbol(None, "CRM")
        self.assertEqual(empty_client.decision, DECISION_INSUFFICIENT_DATA)

    def test_facade_and_company_report_share_fail_closed_result(self) -> None:
        cr = evaluate_portfolio_security_for_symbol(None, "AAPL")
        with patch(
            "services.nabi_intelligence_facade.CandidateRepository"
        ) as candidate_cls, patch(
            "services.nabi_intelligence_facade.ParticipationAssessmentRepository"
        ) as participation_cls, patch(
            "services.nabi_intelligence_facade.UniverseExpansionRepository"
        ), patch(
            "services.nabi_intelligence_facade.production_security_master",
            side_effect=RuntimeError("no sm"),
        ), patch(
            "services.nabi_intelligence_facade.SecurityIntelligenceSnapshotRepository"
        ), patch(
            "services.portfolio_security_decision_service.evaluate_portfolio_security_for_symbol",
            return_value=cr,
        ):
            candidate_cls.return_value.get_by_symbol.return_value = {"symbol": "AAPL"}
            participation_cls.return_value.get_latest.return_value = {
                "participation_status": "Uygun Değil"
            }
            view = get_investment_intelligence(MagicMock(), "AAPL")
        self.assertIs(view.portfolio_security_decision, cr)
        self.assertEqual(view.portfolio_security_decision.decision, cr.decision)
        self.assertEqual(
            view.portfolio_security_decision.exposure_increase_allowed,
            cr.exposure_increase_allowed,
        )
        self.assertEqual(
            list(view.portfolio_security_decision.blocking_reasons),
            list(cr.blocking_reasons),
        )

    def test_yeni_names_are_not_activated_by_the_surface(self) -> None:
        for symbol in ("ADBE", "ADSK", "BIIB", "MU"):
            result = fail_closed_portfolio_security_decision(symbol)
            self.assertNotIn(result.decision, {"CONSIDER_NEW_POSITION", "CONSIDER_TOP_UP"})
            self.assertFalse(result.exposure_increase_allowed)

    def test_view_exposes_canonical_decision_object(self) -> None:
        decision = fail_closed_portfolio_security_decision("MRVL")
        self.assertIsInstance(decision, PortfolioSecurityDecision)
        payload = decision.to_dict()
        self.assertIn("decision", payload)
        self.assertIn("exposure_increase_allowed", payload)
        self.assertIn("blocking_reasons", payload)
        self.assertNotIn("allocated_amount", payload)
        self.assertNotIn("BUY", payload["decision"])
        self.assertNotIn("SELL", payload["decision"])
        self.assertEqual(DEFAULT_RESEARCH_STATUS, "YENI")


if __name__ == "__main__":
    unittest.main()
