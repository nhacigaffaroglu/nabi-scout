from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from services.fund_product_contract import LAYER_CASH_LIKE, PILOT_FUND_SYMBOLS, PILOT_TEFAS_FUND_CODES
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_security_decision_contract import (
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_WATCH,
)
from services.turkiye_fund_navigation import (
    apply_turkiye_fund_report_handoff,
    is_turkiye_fund_nav_identity,
)
from services.turkiye_fund_portfolio_integration import (
    EXPLANATION_INCREASE_BLOCKED,
    ais_satisfies_portfolio_cash,
    apply_portfolio_intelligence_fund_handoff,
    context_from_canonical,
    exposure_maps_to_portfolio_cash,
    format_canonical_new_money_caption,
    format_turkiye_fund_explanation,
    load_turkiye_fund_portfolio_contexts,
    portfolio_intelligence_report_symbols,
    run_turkiye_new_money_uat,
    strategic_layer_for_exposure,
    turkiye_exposure_mappings,
    turkiye_new_money_candidates,
    unavailable_context,
)
from services.turkiye_fund_snapshot_reader import (
    REASON_FI_MISSING,
    REASON_PARTICIPATION_MISSING,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_RESEARCH_NOT_ALLOWED,
    REASON_STALE_FI,
    read_turkiye_fund_canonical,
)
from services.wealth_contract import ASSET_CLASS_CASH
from services.wealth_new_money_allocation import (
    CONCENTRATION_CAP,
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED,
    allocate_new_money,
)
from tests.test_nabi_adviser_8f import _psd
from tests.test_turkiye_fund_8e import FROZEN_FI
from tests.test_turkiye_fund_snapshot_read import (
    FROZEN_EXPOSURE,
    _part_row,
    _seeded_repos,
)
from tests.test_wealth_new_money_allocation import _exposure_policy, _fx, _row, _view

DASHBOARD = Path("pages/1_Dashboard.py")
PI = Path("pages/11_Portfolio_Intelligence.py")
FUND_REPORT = Path("pages/9_Fund_Report.py")
NAV = Path("services/turkiye_fund_navigation.py")
INTEGRATION = Path("services/turkiye_fund_portfolio_integration.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
GOAL = Path("services/wealth_goal_planning.py")
FX = Path("services/fx_conversion_engine.py")
WEALTH_CORE = Path("services/wealth_core_service.py")
BIST = Path("services/bist_refresh_contract.py")
US_SI = Path("services/security_intelligence_engine.py")
UI = Path("components/fund_report_ui.py")


class TurkiyeFundPortfolioIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.part_repo, self.fi_repo = _seeded_repos()

    def _contexts(self, portfolio_view=None):
        return load_turkiye_fund_portfolio_contexts(
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
            portfolio_view=portfolio_view,
        )

    def test_portfolio_intelligence_fund_tr_navigation(self) -> None:
        held = ("AAPL", "SPUS")
        symbols = portfolio_intelligence_report_symbols(held)
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertIn(code, symbols)
        self.assertIn("AAPL", symbols)
        self.assertIn("SPUS", symbols)
        session: dict = {}
        query: dict = {}
        page = apply_portfolio_intelligence_fund_handoff(session, query, "AIS")
        self.assertEqual(page, "pages/9_Fund_Report.py")
        self.assertEqual(session["fund_report_symbol"], "AIS")
        self.assertEqual(session["fund_report_instrument"], "FUND")
        self.assertEqual(session["fund_report_market"], "TR")
        self.assertEqual(query["fund_symbol"], "AIS")
        self.assertNotIn("symbol", query)
        self.assertIsNone(apply_portfolio_intelligence_fund_handoff({}, {}, "SPUS"))
        self.assertIsNone(apply_portfolio_intelligence_fund_handoff({}, {}, "AAPL"))
        source = PI.read_text(encoding="utf-8")
        self.assertIn("apply_portfolio_intelligence_fund_handoff", source)
        self.assertIn("portfolio_intelligence_report_symbols", source)
        turkish_open = source.split("if turkish_page:")[1].split("elif report_page == \"fund_report\":")[0]
        self.assertNotIn('query_params["symbol"]', turkish_open)
        self.assertIn("st.switch_page(turkish_page)", turkish_open)

    def test_dashboard_navigation_regression(self) -> None:
        dashboard = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("apply_turkiye_fund_report_handoff", dashboard)
        self.assertIn("_render_turkiye_fund_section", dashboard)
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertTrue(is_turkiye_fund_nav_identity(code, instrument="FUND", market="TR"))
        handoff = apply_turkiye_fund_report_handoff({}, {}, "ZPE")
        self.assertEqual(handoff.instrument, "FUND")
        self.assertEqual(handoff.market, "TR")
        self.assertFalse(handoff.attach_us_etf_live)

    def test_snapshot_only_portfolio_context(self) -> None:
        contexts = {row.fund_code: row for row in self._contexts()}
        expected = {
            "AIS": (PARTICIPATION_STATUS_UYGUN, 70.39, "WATCH", LAYER_CASH_LIKE, DECISION_WATCH, False),
            "ZPE": (PARTICIPATION_STATUS_UYGUN, 66.32, "WATCH", "equity", DECISION_WATCH, False),
            "IAT": (PARTICIPATION_STATUS_UYGUN, 60.49, "NEUTRAL", "sukuk", DECISION_WATCH, False),
        }
        for code, (status, score, fi_state, exposure, eight_e, increase) in expected.items():
            row = contexts[code]
            self.assertEqual(row.instrument, "FUND")
            self.assertEqual(row.market, "TR")
            self.assertFalse(row.is_holding)
            self.assertEqual(row.participation_status, status)
            self.assertTrue(row.research_allowed)
            self.assertEqual(row.fi_score, score)
            self.assertEqual(row.fi_state, fi_state)
            self.assertEqual(row.primary_exposure, exposure)
            self.assertEqual(row.eight_e, eight_e)
            self.assertEqual(row.increase_allowed, increase)
            self.assertIsNone(row.unavailable_reason)

    def test_held_and_non_held_context(self) -> None:
        view = _view(
            [_row("ZPE", market_value=1500, weight_pct=15, asset_class="fund", price=10)]
        )
        contexts = {row.fund_code: row for row in self._contexts(view)}
        self.assertTrue(contexts["ZPE"].is_holding)
        self.assertEqual(contexts["ZPE"].market_value, 1500)
        self.assertFalse(contexts["AIS"].is_holding)
        self.assertFalse(contexts["IAT"].is_holding)
        self.assertFalse(contexts["ZPE"].increase_allowed)
        self.assertEqual(contexts["ZPE"].eight_e, DECISION_WATCH)

    def test_ais_cash_like_is_not_portfolio_cash(self) -> None:
        ais = {row.fund_code: row for row in self._contexts()}["AIS"]
        self.assertEqual(ais.instrument, "FUND")
        self.assertEqual(ais.primary_exposure, LAYER_CASH_LIKE)
        self.assertEqual(strategic_layer_for_exposure(ais.primary_exposure), LAYER_CASH_LIKE)
        self.assertNotEqual(strategic_layer_for_exposure(ais.primary_exposure), ASSET_CLASS_CASH)
        self.assertFalse(exposure_maps_to_portfolio_cash(ais.primary_exposure))
        self.assertFalse(ais_satisfies_portfolio_cash(ais))
        mapping = turkiye_exposure_mappings([ais])["AIS"][0]
        self.assertEqual(mapping.exposure_bucket, LAYER_CASH_LIKE)
        self.assertIn("NOT_PORTFOLIO_CASH", mapping.limitations)
        self.assertNotEqual(mapping.exposure_bucket, ASSET_CLASS_CASH)

    def test_zpe_equity_and_iat_sukuk_mapping(self) -> None:
        contexts = {row.fund_code: row for row in self._contexts()}
        self.assertEqual(strategic_layer_for_exposure(contexts["ZPE"].primary_exposure), "equity")
        self.assertEqual(strategic_layer_for_exposure(contexts["IAT"].primary_exposure), "sukuk")
        mappings = turkiye_exposure_mappings(self._contexts())
        self.assertEqual(mappings["ZPE"][0].exposure_bucket, "equity")
        self.assertEqual(mappings["IAT"][0].exposure_bucket, "sukuk")

    def test_hybrid_off_and_generic_8e(self) -> None:
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        uat = self._uat()
        self.assertFalse(uat.plan.hybrid_allocation_active)
        for context in self._contexts():
            self.assertIsNotNone(context.decision)
            self.assertEqual(context.decision.decision, DECISION_WATCH)
            self.assertFalse(context.decision.exposure_increase_allowed)

    def _uat(self, *, view=None, held_symbol=None, extra_decisions=(), **kwargs):
        if view is None:
            rows = [_row("AAPL", market_value=3000, weight_pct=30)]
            if held_symbol:
                rows.append(
                    _row(
                        held_symbol,
                        market_value=1000,
                        weight_pct=10,
                        asset_class="fund",
                        price=10,
                    )
                )
                rows.append(_row("SUKUK1", market_value=6000, weight_pct=60, asset_class="sukuk"))
            else:
                rows.append(_row("SUKUK1", market_value=7000, weight_pct=70, asset_class="sukuk"))
            view = _view(rows)
        contexts = self._contexts(view)
        return run_turkiye_new_money_uat(
            portfolio_view=view,
            policy=_exposure_policy(equity=50, sukuk=40, cash=10),
            contexts=contexts,
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            conversion=_fx(),
            extra_decisions=(
                _psd("AAPL", DECISION_HOLD, increase=True),
                _psd("SUKUK1", DECISION_HOLD, increase=True),
                *extra_decisions,
            ),
            price_by_symbol={"AIS": 10, "ZPE": 10, "IAT": 10},
            **kwargs,
        )

    def test_increase_allowed_false_allocation_zero(self) -> None:
        uat = self._uat()
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertEqual(uat.by_fund[code], Decimal("0"))
            self.assertIn(REASON_EXPOSURE_INCREASE_NOT_ALLOWED, uat.skip_reasons[code])
        self.assertEqual(uat.turkish_allocated, Decimal("0"))

    def test_held_watch_top_up_zero(self) -> None:
        uat = self._uat(held_symbol="AIS")
        self.assertEqual(uat.by_fund["AIS"], Decimal("0"))
        self.assertIn(REASON_EXPOSURE_INCREASE_NOT_ALLOWED, uat.skip_reasons["AIS"])
        ais = {row.fund_code: row for row in self._contexts(
            _view([_row("AIS", market_value=1000, weight_pct=10, asset_class="fund", price=10)])
        )}["AIS"]
        self.assertTrue(ais.is_holding)

    def test_non_held_watch_new_position_zero(self) -> None:
        uat = self._uat()
        candidates = {row["symbol"] for row in turkiye_new_money_candidates(
            self._contexts(),
            price_by_symbol={"AIS": 10, "ZPE": 10, "IAT": 10},
        )}
        self.assertEqual(candidates, set(PILOT_TEFAS_FUND_CODES))
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertEqual(uat.by_fund[code], Decimal("0"))

    def test_sixty_thousand_try_scenario(self) -> None:
        uat = self._uat()
        self.assertEqual(uat.plan.input_amount, Decimal("60000"))
        self.assertEqual(uat.plan.currency, "TRY")
        self.assertEqual(uat.turkish_allocated, Decimal("0"))
        self.assertEqual(uat.total_allocated, uat.other_allocated)
        self.assertEqual(uat.total_allocated + uat.residual_cash, Decimal("60000"))
        self.assertGreaterEqual(uat.residual_cash, Decimal("0"))
        rec_symbols = {row.symbol for row in uat.plan.recommendations}
        self.assertTrue(rec_symbols.isdisjoint(PILOT_TEFAS_FUND_CODES))

    def test_missing_upstream_evidence_fail_closed(self) -> None:
        from services.turkiye_fund_persistence import (
            MemoryParticipationAssessmentRepository,
            MemorySecurityIntelligenceSnapshotRepository,
        )

        cases = {
            REASON_PARTICIPATION_MISSING: (
                MemoryParticipationAssessmentRepository(),
                self.fi_repo,
            ),
            REASON_FI_MISSING: (
                self.part_repo,
                MemorySecurityIntelligenceSnapshotRepository(),
            ),
        }
        for reason, (part, fi) in cases.items():
            contexts = load_turkiye_fund_portfolio_contexts(
                participation_repo=part,
                snapshot_repo=fi,
                fund_codes=("AIS",),
            )
            self.assertEqual(contexts[0].unavailable_reason, reason)
            self.assertFalse(contexts[0].increase_allowed)
            self.assertEqual(contexts[0].eight_e, DECISION_INSUFFICIENT_DATA)
            uat = run_turkiye_new_money_uat(
                portfolio_view=_view([_row("AAPL", market_value=10000, weight_pct=100)]),
                policy=_exposure_policy(equity=80, sukuk=10, cash=10),
                contexts=contexts,
                extra_decisions=(_psd("AAPL", DECISION_HOLD, increase=True),),
                price_by_symbol={"AIS": 10},
                conversion=_fx(),
            )
            self.assertEqual(uat.by_fund["AIS"], Decimal("0"))
            self.assertFalse(turkiye_new_money_candidates(contexts, price_by_symbol={"AIS": 10}))

        blocked = MemoryParticipationAssessmentRepository()
        blocked.rows.append(_part_row("AIS", status=PARTICIPATION_STATUS_UYGUN_DEGIL))
        not_uygun = load_turkiye_fund_portfolio_contexts(
            participation_repo=blocked,
            snapshot_repo=self.fi_repo,
            fund_codes=("AIS",),
        )
        self.assertEqual(not_uygun[0].unavailable_reason, REASON_PARTICIPATION_NOT_UYGUN)

        denied = MemoryParticipationAssessmentRepository()
        denied.rows.append(_part_row("AIS", research_allowed=False))
        research = load_turkiye_fund_portfolio_contexts(
            participation_repo=denied,
            snapshot_repo=self.fi_repo,
            fund_codes=("AIS",),
        )
        self.assertEqual(research[0].unavailable_reason, REASON_RESEARCH_NOT_ALLOWED)

        stale_ctx = unavailable_context("IAT", REASON_STALE_FI)
        self.assertFalse(stale_ctx.increase_allowed)
        self.assertEqual(format_turkiye_fund_explanation(stale_ctx).allocation_try, Decimal("0"))

        missing_exposure = unavailable_context("ZPE", "ECONOMIC_EXPOSURE_MISSING")
        self.assertEqual(strategic_layer_for_exposure(missing_exposure.primary_exposure), None)
        self.assertFalse(turkiye_exposure_mappings([missing_exposure]))

        missing_8e = unavailable_context("AIS", "FUND_8E_DECISION_MISSING")
        self.assertIsNone(missing_8e.decision)
        self.assertEqual(missing_8e.eight_e, DECISION_INSUFFICIENT_DATA)

    def test_concentration_unchanged(self) -> None:
        self.assertEqual(CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT, 20.0)
        self.assertEqual(CONCENTRATION_CAP, Decimal("0.20"))

    def test_deterministic_explanation_context(self) -> None:
        ais = {row.fund_code: row for row in self._contexts()}["AIS"]
        explanation = format_turkiye_fund_explanation(ais, allocation_try=0)
        self.assertIn("Katılım Uygun", explanation.summary_tr)
        self.assertIn("FI 70.39 WATCH", explanation.summary_tr)
        self.assertIn("8E WATCH", explanation.summary_tr)
        self.assertIn(EXPLANATION_INCREASE_BLOCKED, explanation.summary_tr)
        self.assertIn("Allocation 0 TRY", explanation.summary_tr)
        self.assertFalse(explanation.increase_allowed)
        self.assertEqual(explanation.exposure, LAYER_CASH_LIKE)
        caption = format_canonical_new_money_caption(increase_allowed=False, eight_e="WATCH")
        self.assertIn(EXPLANATION_INCREASE_BLOCKED, caption)
        self.assertIn("Allocation 0 TRY", caption)
        self.assertIn("Yeni para artışına izin verilmiyor", UI.read_text(encoding="utf-8"))
        self.assertIn("Allocation 0 TRY", UI.read_text(encoding="utf-8"))
        self.assertNotIn("allocate_new_money", UI.read_text(encoding="utf-8"))

    def test_no_tefas_kap_fmp_fresh_compute(self) -> None:
        forbidden = (
            "FMPClient",
            "default_tefas_fund_provider",
            "evaluate_official_fund_intelligence",
            "evaluate_turkiye_fund_participation",
            "evaluate_official_fund_decision",
            "run_turkiye_fund_refresh",
        )
        source = INTEGRATION.read_text(encoding="utf-8")
        for token in forbidden:
            self.assertNotIn(token, source)
        with patch(
            "services.fmp_client.FMPClient.from_streamlit_secrets",
            side_effect=AssertionError("fmp_called"),
        ), patch(
            "services.official_tefas_product.default_tefas_fund_provider",
            side_effect=AssertionError("tefas_called"),
        ), patch(
            "services.official_kap_pdr_evidence.load_captured_pdr_holdings",
            side_effect=AssertionError("kap_called"),
        ), patch(
            "services.fund_intelligence_engine.evaluate_official_fund_intelligence",
            side_effect=AssertionError("fi_called"),
        ), patch(
            "services.official_turkiye_fund_participation.evaluate_turkiye_fund_participation",
            side_effect=AssertionError("participation_called"),
        ):
            self._contexts()
            self._uat()

    def test_no_production_writes(self) -> None:
        source = INTEGRATION.read_text(encoding="utf-8")
        for token in (".insert(", ".upsert(", ".update(", ".delete(", "append_snapshot"):
            self.assertNotIn(token, source)
        self.assertNotIn("post_transaction", source)

    def test_sp_funds_bist_us_goal_wealth_fx_regression(self) -> None:
        from services.fund_intelligence_engine import evaluate_official_fund_intelligence

        self.assertFalse(is_turkiye_fund_nav_identity("SPUS"))
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
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        integration = INTEGRATION.read_text(encoding="utf-8")
        self.assertNotIn("wealth_goal_planning", integration)
        self.assertNotIn("fx_conversion_engine", integration)
        self.assertNotIn("wealth_core_service", integration)
        self.assertTrue(GOAL.is_file())
        self.assertTrue(FX.is_file())
        self.assertTrue(WEALTH_CORE.is_file())
        self.assertIn("pages/4_Company_Report.py", PI.read_text(encoding="utf-8"))
        baseline = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_view([_row("AAPL", market_value=10000, weight_pct=100)]),
            policy=_exposure_policy(equity=80, sukuk=10, cash=10),
            conversion=_fx(),
        )
        self.assertTrue(callable(allocate_new_money))
        self.assertGreaterEqual(baseline.residual_cash, Decimal("0"))

    def test_frozen_canonical_scores(self) -> None:
        for code, (score, state) in FROZEN_FI.items():
            read = read_turkiye_fund_canonical(
                participation_repo=self.part_repo,
                snapshot_repo=self.fi_repo,
                fund_code=code,
            )
            self.assertEqual(read.fund_intelligence.score, score)
            self.assertEqual(read.fund_intelligence.state, state)
            ctx = context_from_canonical(read)
            self.assertEqual(ctx.fi_score, score)
            layer, geo, _conf = FROZEN_EXPOSURE[code]
            self.assertEqual(ctx.primary_exposure, layer)
            self.assertEqual(ctx.geography, geo)


if __name__ == "__main__":
    unittest.main()
