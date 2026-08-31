from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from services.fund_product_contract import LAYER_CASH_LIKE, PILOT_FUND_SYMBOLS, PILOT_TEFAS_FUND_CODES
from services.fund_report_service import (
    build_fund_report_view,
    turkiye_fund_report_canonical_from_read,
    validate_fund_report_entry,
)
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import DECISION_INSUFFICIENT_DATA, DECISION_WATCH
from services.portfolio_security_decision_service import evaluate_portfolio_security_for_symbol
from services.turkiye_fund_snapshot_reader import (
    REASON_FI_MISSING,
    REASON_INCOMPATIBLE_METHODOLOGY,
    REASON_PARTICIPATION_MISSING,
    REASON_RESEARCH_NOT_ALLOWED,
    REASON_STALE_FI,
    SnapshotReadError,
    is_turkiye_fund_production_identity,
    read_turkiye_fund_canonical,
)
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_turkiye_fund_8e import FROZEN_FI
from tests.test_turkiye_fund_snapshot_read import (
    ACCEPTED_FI_IDS,
    ACCEPTED_PARTICIPATION_IDS,
    _seeded_repos,
)

PAGE = Path("pages/9_Fund_Report.py")
REPORT = Path("services/fund_report_service.py")
UI = Path("components/fund_report_ui.py")
SURFACE = Path("services/portfolio_security_decision_service.py")
FACADE = Path("services/nabi_intelligence_facade.py")
READER = Path("services/turkiye_fund_snapshot_reader.py")
ORCHESTRATOR = Path("services/turkiye_fund_refresh_orchestrator.py")
BIST = Path("services/bist_refresh_contract.py")
BIST_ORCH = Path("services/bist_refresh_orchestrator.py")
US_SI = Path("services/security_intelligence_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")


class _Client:
    def table(self, _name: str):
        raise AssertionError("unexpected_table_access")


class TurkiyeFundConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.part_repo, self.fi_repo = _seeded_repos()

    def _canonical(self, code: str):
        return read_turkiye_fund_canonical(
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
            fund_code=code,
            is_holding=True,
            portfolio_weight=5.0,
        )

    def test_routing_uses_instrument_market_identity(self) -> None:
        self.assertTrue(is_turkiye_fund_production_identity("AIS"))
        self.assertTrue(is_turkiye_fund_production_identity("ZPE", instrument="FUND", market="TR"))
        self.assertFalse(is_turkiye_fund_production_identity("AIS", instrument="EQUITY", market="US"))
        self.assertFalse(is_turkiye_fund_production_identity("SPUS", instrument="FUND", market="US"))
        self.assertFalse(is_turkiye_fund_production_identity("ASELS", instrument="EQUITY", market="TR"))
        self.assertFalse(is_turkiye_fund_production_identity("AAPL"))

    def test_fund_report_uses_snapshot_reader(self) -> None:
        for code, (score, state) in FROZEN_FI.items():
            allowed, reason = validate_fund_report_entry(code, tracked_row=None)
            self.assertTrue(allowed)
            self.assertIsNone(reason)
            view = build_fund_report_view(
                code,
                tracked_row=None,
                canonical=turkiye_fund_report_canonical_from_read(self._canonical(code)),
            )
            self.assertTrue(view.entry_allowed)
            self.assertEqual(view.canonical.participation_status, PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(view.canonical.research_allowed)
            self.assertEqual(view.canonical.fi_score, score)
            self.assertEqual(view.canonical.fi_state, state)
            self.assertEqual(view.canonical.eight_e, DECISION_WATCH)
            self.assertFalse(view.canonical.increase_allowed)
            self.assertEqual(view.canonical.instrument, "FUND")
            self.assertEqual(view.canonical.market, "TR")
        self.assertEqual(
            build_fund_report_view(
                "AIS",
                tracked_row=None,
                canonical=turkiye_fund_report_canonical_from_read(self._canonical("AIS")),
            ).canonical.exposure,
            LAYER_CASH_LIKE,
        )
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn("load_turkiye_fund_canonical_from_client", page)
        self.assertIn("is_turkiye_fund_production_identity", page)
        self.assertNotIn("evaluate_official_fund_decision", page)
        self.assertNotIn("evaluate_official_fund_intelligence", REPORT.read_text(encoding="utf-8"))

    def test_no_fresh_compute_on_consumer_path(self) -> None:
        for path in (PAGE, REPORT, UI, SURFACE, FACADE):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("evaluate_official_fund_decision", source)
            self.assertNotIn("evaluate_official_fund_intelligence", source)
            self.assertNotIn("allocate_new_money", source)
        self.assertIn("load_turkiye_fund_canonical_from_client", SURFACE.read_text(encoding="utf-8"))
        self.assertIn("evaluate_official_fund_decision", ORCHESTRATOR.read_text(encoding="utf-8"))
        with patch(
            "services.official_tefas_product.default_tefas_fund_provider",
            side_effect=AssertionError("tefas_called"),
        ), patch(
            "services.fund_intelligence_engine.evaluate_official_fund_intelligence",
            side_effect=AssertionError("fi_called"),
        ), patch(
            "services.official_turkiye_fund_participation.evaluate_turkiye_fund_participation",
            side_effect=AssertionError("participation_called"),
        ), patch(
            "services.wealth_new_money_allocation.allocate_new_money",
            side_effect=AssertionError("new_money_called"),
        ):
            for code in PILOT_TEFAS_FUND_CODES:
                loaded = self._canonical(code)
                view = build_fund_report_view(
                    code,
                    tracked_row=None,
                    canonical=turkiye_fund_report_canonical_from_read(loaded),
                )
                self.assertEqual(view.canonical.eight_e, DECISION_WATCH)

    def test_missing_and_incompatible_fail_closed(self) -> None:
        empty = type("Empty", (), {})()
        for reason, loader in (
            (REASON_PARTICIPATION_MISSING, lambda: read_turkiye_fund_canonical(
                participation_repo=type("P", (), {"get_recent_history": lambda *_a, **_k: []})(),
                snapshot_repo=self.fi_repo,
                fund_code="AIS",
            )),
            (REASON_FI_MISSING, lambda: read_turkiye_fund_canonical(
                participation_repo=self.part_repo,
                snapshot_repo=type("F", (), {"get_recent_history": lambda *_a, **_k: []})(),
                fund_code="AIS",
            )),
        ):
            with self.assertRaises(SnapshotReadError) as raised:
                loader()
            self.assertEqual(raised.exception.reason, reason)
        view = build_fund_report_view(
            "AIS",
            tracked_row=None,
            canonical_unavailable_reason=REASON_STALE_FI,
        )
        self.assertTrue(view.entry_allowed)
        self.assertEqual(view.canonical_unavailable_reason, REASON_STALE_FI)
        self.assertIsNone(view.canonical)
        self.assertIn(REASON_RESEARCH_NOT_ALLOWED, {REASON_RESEARCH_NOT_ALLOWED, REASON_INCOMPATIBLE_METHODOLOGY})

    def test_8e_surface_uses_reader_and_fail_closes(self) -> None:
        decision = evaluate_portfolio_security_for_symbol(None, "AIS")
        self.assertEqual(decision.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(decision.exposure_increase_allowed)
        with patch(
            "services.portfolio_security_decision_service.is_turkiye_fund_production_identity",
            return_value=True,
        ), patch(
            "services.portfolio_security_decision_service.load_turkiye_fund_canonical_from_client",
            side_effect=SnapshotReadError(REASON_FI_MISSING, fund_code="AIS"),
        ), patch(
            "services.official_tefas_product.default_tefas_fund_provider",
            side_effect=AssertionError("tefas_called"),
        ):
            blocked = evaluate_portfolio_security_for_symbol(_Client(), "AIS")
        self.assertEqual(blocked.decision, DECISION_INSUFFICIENT_DATA)
        loaded = self._canonical("IAT")
        with patch(
            "services.portfolio_security_decision_service.is_turkiye_fund_production_identity",
            return_value=True,
        ), patch(
            "services.portfolio_security_decision_service._portfolio_view",
            return_value=None,
        ), patch(
            "services.portfolio_security_decision_service.load_turkiye_fund_canonical_from_client",
            return_value=loaded,
        ):
            live = evaluate_portfolio_security_for_symbol(_Client(), "IAT")
        self.assertEqual(live.decision, DECISION_WATCH)
        self.assertFalse(live.exposure_increase_allowed)
        self.assertEqual(live.security_intelligence_score, 60.49)

    def test_sp_funds_bist_us_and_persistence_isolation(self) -> None:
        from services.fund_intelligence_engine import evaluate_official_fund_intelligence
        from services.nabi_intelligence_facade import get_investment_intelligence

        self.assertFalse(is_turkiye_fund_production_identity("SPUS"))
        for symbol in PILOT_FUND_SYMBOLS:
            allowed, _reason = validate_fund_report_entry(symbol, tracked_row=None)
            self.assertFalse(allowed)
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        sp = default_official_sp_funds_provider()
        tefas = default_tefas_fund_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertTrue(sp.supports(symbol))
            self.assertFalse(tefas.supports(symbol))
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertIn("persist_si", BIST_ORCH.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        self.assertNotIn("read_turkiye_fund_canonical", ORCHESTRATOR.read_text(encoding="utf-8"))
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        self.assertTrue(callable(allocate_new_money))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertIn("is_turkiye_fund_production_identity", FACADE.read_text(encoding="utf-8"))
        self.assertTrue(callable(get_investment_intelligence))
        self.assertEqual(ACCEPTED_PARTICIPATION_IDS["AIS"], "8e9a0c03-ece7-40a1-9c04-98a2baf49350")
        self.assertEqual(ACCEPTED_FI_IDS["ZPE"], "90ad219d-cbdc-4b21-9319-11a9d11b58a6")


if __name__ == "__main__":
    unittest.main()
