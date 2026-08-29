from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.nabi_intelligence_facade import get_investment_intelligence
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.security_intelligence_service import (
    SecurityIntelligenceService,
    build_canonical_security_intelligence_inputs,
    explicit_persisted_research_allowed,
)


PAGE = Path("pages/4_Company_Report.py")
FACADE = Path("services/nabi_intelligence_facade.py")
SERVICE = Path("services/security_intelligence_service.py")


def _company_report_si(
    symbol: str,
    *,
    candidate,
    snapshot,
    queue_row,
    security_resolution=None,
    client=None,
):
    facts, participation = build_canonical_security_intelligence_inputs(
        symbol,
        candidate=candidate,
        participation_snapshot=snapshot,
        queue_row=queue_row,
        security_resolution=security_resolution,
        client=client,
    )
    view = SecurityIntelligenceService().evaluate(facts, participation)
    return facts, participation, view


class ExplicitResearchAllowedParityTests(unittest.TestCase):
    def test_uygun_does_not_imply_research_allowed(self) -> None:
        self.assertIsNone(
            explicit_persisted_research_allowed(
                snapshot={"participation_status": PARTICIPATION_STATUS_UYGUN}
            )
        )
        _, participation = build_canonical_security_intelligence_inputs(
            "CRM",
            participation_snapshot={"participation_status": PARTICIPATION_STATUS_UYGUN},
        )
        self.assertEqual(participation.status, PARTICIPATION_STATUS_UYGUN)
        self.assertIsNone(participation.research_allowed)

    def test_reads_persisted_queue_boolean(self) -> None:
        self.assertTrue(
            explicit_persisted_research_allowed(queue_row={"research_allowed": True})
        )
        self.assertFalse(
            explicit_persisted_research_allowed(queue_row={"research_allowed": False})
        )


class CompanyReportFacadeInputParityTests(unittest.TestCase):
    def test_shared_helper_is_the_only_si_input_path(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        facade = FACADE.read_text(encoding="utf-8")
        service = SERVICE.read_text(encoding="utf-8")
        self.assertIn("build_canonical_security_intelligence_inputs", page)
        self.assertIn("build_canonical_security_intelligence_inputs", facade)
        self.assertIn("allow_sec_cache_replay=True", service)
        self.assertNotIn("evaluate_research_eligibility", service)
        self.assertNotIn("Uygun =>", service)
        self.assertNotIn("allow_sec_cache_replay=False", facade)
        self.assertNotIn("get_investment_intelligence", page)

    def test_same_persisted_state_same_si(self) -> None:
        samples = (
            (
                "CRM",
                {"symbol": "CRM", "revenue": 37_000, "roic": 18, "pe_ratio": 28},
                {"participation_status": PARTICIPATION_STATUS_UYGUN},
                {"research_allowed": True},
            ),
            (
                "AAPL",
                {"symbol": "AAPL", "revenue": 390_000, "roic": 40, "pe_ratio": 30},
                {"participation_status": PARTICIPATION_STATUS_UYGUN_DEGIL},
                {"research_allowed": False},
            ),
            (
                "MRVL",
                {"symbol": "MRVL", "revenue": 5_000, "roic": 8, "pe_ratio": 40},
                {"participation_status": PARTICIPATION_STATUS_KONTROL_ET},
                {"research_allowed": False},
            ),
        )
        for symbol, candidate, snapshot, queue_row in samples:
            with self.subTest(symbol=symbol):
                cr_facts, cr_part, cr_view = _company_report_si(
                    symbol,
                    candidate=candidate,
                    snapshot=snapshot,
                    queue_row=queue_row,
                )
                facade_facts, facade_part = build_canonical_security_intelligence_inputs(
                    symbol,
                    candidate=candidate,
                    participation_snapshot=snapshot,
                    queue_row=queue_row,
                )
                facade_view = SecurityIntelligenceService().evaluate(
                    facade_facts, facade_part
                )
                self.assertEqual(cr_facts.to_dict(), facade_facts.to_dict())
                self.assertEqual(cr_part.to_dict(), facade_part.to_dict())
                self.assertEqual(cr_view.to_dict(), facade_view.to_dict())
                self.assertEqual(cr_part.research_allowed, queue_row["research_allowed"])
                self.assertEqual(cr_view.research_allowed, queue_row["research_allowed"])

    def test_facade_entry_uses_explicit_research_allowed(self) -> None:
        client = MagicMock()
        with patch(
            "services.nabi_intelligence_facade.CandidateRepository"
        ) as candidate_cls, patch(
            "services.nabi_intelligence_facade.ParticipationAssessmentRepository"
        ) as participation_cls, patch(
            "services.nabi_intelligence_facade.UniverseExpansionRepository"
        ) as queue_cls, patch(
            "services.nabi_intelligence_facade.production_security_master",
            side_effect=RuntimeError("no sm"),
        ), patch(
            "services.nabi_intelligence_facade.SecurityIntelligenceSnapshotRepository"
        ):
            candidate_cls.return_value.get_by_symbol.return_value = {
                "id": "crm-1",
                "symbol": "CRM",
                "company_name": "Salesforce",
                "nabi_score": 70.0,
            }
            participation_cls.return_value.get_latest.return_value = {
                "participation_status": PARTICIPATION_STATUS_UYGUN,
            }
            queue_cls.return_value.get_by_symbol.return_value = {"research_allowed": True}
            view = get_investment_intelligence(client, "CRM")
            cr_facts, cr_part, cr_view = _company_report_si(
                "CRM",
                candidate=candidate_cls.return_value.get_by_symbol.return_value,
                snapshot=participation_cls.return_value.get_latest.return_value,
                queue_row={"research_allowed": True},
            )
        self.assertEqual(view.security_intelligence_state, cr_view.investment_state)
        self.assertEqual(view.security_intelligence_overall, cr_view.overall_score)
        self.assertEqual(cr_part.research_allowed, True)
        self.assertEqual(cr_view.research_allowed, True)
        self.assertIsNotNone(cr_facts.completeness_pct)


if __name__ == "__main__":
    unittest.main()
