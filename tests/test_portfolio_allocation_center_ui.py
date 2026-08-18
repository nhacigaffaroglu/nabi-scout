from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.portfolio_allocation_center_ui import (
    APPLIED_WEIGHTS_KEY,
    BUCKET_LABELS,
    CONTRIB_AMOUNT_KEY,
    FX_REQUIRED_COPY,
    HEADING,
    PARTIAL_NOTE,
    PLANNING_FX_SESSION_KEY,
    PLANNED_CONTRIBUTION_LABEL,
    ROUTING_HEADING,
    SIMULATION_NOTE,
    UNCONFIGURED_ROUTING,
    build_allocation_for_ui,
    flatten_allocation_text,
    policy_from_session,
    present_allocation_center,
    remaining_target_pct,
    render_portfolio_allocation_center,
    validate_target_weights,
)
from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    AllocationPolicy,
    AllocationPolicyStatus,
    AllocationProvenance,
    AllocationTarget,
    build_allocation_intelligence,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from tests.test_portfolio_allocation_intelligence import (
    _complete_usd_view,
    _partial_bist_view,
)

ACCOUNT = "acc-1"
UI = Path("components/portfolio_allocation_center_ui.py")
PI_PAGE = Path("pages/11_Portfolio_Intelligence.py")
ENGINE = Path("services/portfolio_allocation_intelligence.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    ".update(",
)


def _policy_70_30() -> dict:
    return {
        APPLIED_WEIGHTS_KEY: {
            "equity": 70.0,
            "etf": 30.0,
            "sukuk": 0.0,
            "cash": 0.0,
            "other": 0.0,
        }
    }


def _row(*, symbol: str, asset_class: str, market_value: float, weight_pct: float) -> PositionValuationRow:
    return PositionValuationRow(
        position_id=f"p-{symbol}",
        account_id=ACCOUNT,
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class=asset_class,
        account_name="Broker",
        quantity=1,
        average_cost=10,
        valuation_currency="USD",
        price=110,
        price_available=True,
        market_value=market_value,
        cost_basis=10,
        unrealized_pl=100,
        weight_pct=weight_pct,
        is_cash=False,
        included_in_base_totals=True,
    )


def _live_like_view() -> PortfolioIntelligenceView:
    equity_mv = 83.3627
    etf_mv = 16.6373
    total = equity_mv + etf_mv
    priced = [
        _row(symbol="AAPL", asset_class="equity", market_value=equity_mv, weight_pct=83.3627),
        _row(symbol="SPUS", asset_class="etf", market_value=etf_mv, weight_pct=16.6373),
    ]
    foreign = [
        PositionValuationRow(
            position_id="p-BIMAS",
            account_id=ACCOUNT,
            asset_id="as-BIMAS",
            symbol="BIMAS",
            asset_class="equity",
            account_name="Broker",
            quantity=1,
            average_cost=10,
            valuation_currency="TRY",
            price=None,
            price_available=False,
            market_value=None,
            cost_basis=10,
            unrealized_pl=None,
            weight_pct=None,
            is_cash=False,
            included_in_base_totals=False,
        ),
        PositionValuationRow(
            position_id="p-ASELS",
            account_id=ACCOUNT,
            asset_id="as-ASELS",
            symbol="ASELS",
            asset_class="equity",
            account_name="Broker",
            quantity=1,
            average_cost=10,
            valuation_currency="TRY",
            price=None,
            price_available=False,
            market_value=None,
            cost_basis=10,
            unrealized_pl=None,
            weight_pct=None,
            is_cash=False,
            included_in_base_totals=False,
        ),
        PositionValuationRow(
            position_id="p-TUPRS",
            account_id=ACCOUNT,
            asset_id="as-TUPRS",
            symbol="TUPRS",
            asset_class="equity",
            account_name="Broker",
            quantity=1,
            average_cost=10,
            valuation_currency="TRY",
            price=None,
            price_available=False,
            market_value=None,
            cost_basis=10,
            unrealized_pl=None,
            weight_pct=None,
            is_cash=False,
            included_in_base_totals=False,
        ),
    ]
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=total,
        priced_total_cost_basis=20,
        priced_total_unrealized_pl=200,
        priced_position_count=2,
        unpriced_position_count=3,
        foreign_currency_position_count=3,
        total_position_count=5,
        mixed_currency_warning=True,
        fx_supported=False,
        priced_positions=priced,
        unpriced_positions=foreign,
        foreign_currency_positions=foreign,
        asset_class_allocation=[AllocationSlice("equity", "equity", equity_mv, 83.3627)],
        account_allocation=[AllocationSlice(ACCOUNT, "Broker", total, 100.0)],
        health=PortfolioHealthMetrics(83.3627, 100.0, 83.3627, 0.0, 100.0, 40.0),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


def _empty_view() -> PortfolioIntelligenceView:
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=0,
        priced_total_cost_basis=0,
        priced_total_unrealized_pl=0,
        priced_position_count=0,
        unpriced_position_count=0,
        foreign_currency_position_count=0,
        total_position_count=0,
        mixed_currency_warning=False,
        fx_supported=False,
        priced_positions=[],
        unpriced_positions=[],
        foreign_currency_positions=[],
        asset_class_allocation=[],
        account_allocation=[],
        health=PortfolioHealthMetrics(0, 0, 0, 0, 0, 100),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


class PlacementTests(unittest.TestCase):
    def test_pi_hosts_allocation_center(self) -> None:
        source = PI_PAGE.read_text(encoding="utf-8")
        self.assertIn("render_portfolio_allocation_center", source)
        hero = source.index("render_portfolio_executive_hero(")
        decision = source.index("render_portfolio_decision_center(")
        alloc = source.index("render_portfolio_allocation_center(")
        self.assertLess(hero, decision)
        self.assertLess(decision, alloc)
        self.assertEqual(source.count("render_portfolio_allocation_center("), 1)


class TargetPolicyTests(unittest.TestCase):
    def test_starts_unconfigured(self) -> None:
        view = build_allocation_for_ui(_complete_usd_view(), session_state={})
        presented = present_allocation_center(view, draft_weights={})
        self.assertFalse(presented.configured)
        self.assertEqual(view.target_policy_status, AllocationPolicyStatus.TARGET_NOT_CONFIGURED)
        self.assertIsNone(policy_from_session({}))

    def test_valid_100_target_accepted(self) -> None:
        policy = policy_from_session(_policy_70_30())
        self.assertIsNotNone(policy)
        self.assertEqual(policy.provenance, AllocationProvenance.USER_DEFINED)
        view = build_allocation_for_ui(_complete_usd_view(), session_state=_policy_70_30())
        self.assertEqual(view.target_policy_status, AllocationPolicyStatus.CONFIGURED)

    def test_invalid_total_rejected(self) -> None:
        self.assertIsNotNone(validate_target_weights({"equity": 70, "etf": 20, "sukuk": 0, "cash": 0, "other": 0}))
        self.assertIsNone(
            policy_from_session(
                {APPLIED_WEIGHTS_KEY: {"equity": 70, "etf": 20, "sukuk": 0, "cash": 0, "other": 0}}
            )
        )
        self.assertAlmostEqual(remaining_target_pct({"equity": 70, "etf": 20}), 10.0)

    def test_negative_target_rejected(self) -> None:
        self.assertEqual(
            validate_target_weights({"equity": -1, "etf": 101, "sukuk": 0, "cash": 0, "other": 0}),
            "Hedef ağırlık negatif olamaz.",
        )

    def test_no_auto_normalization(self) -> None:
        source = UI.read_text(encoding="utf-8")
        self.assertIn("otomatik dengeleme yok", source)
        self.assertNotIn("def normalize", source)
        weights = {"equity": 70, "etf": 20, "sukuk": 0, "cash": 0, "other": 0}
        self.assertAlmostEqual(sum(weights.values()), 90)
        self.assertIsNotNone(validate_target_weights(weights))

    def test_session_only_target_and_fx_key_reused(self) -> None:
        source = UI.read_text(encoding="utf-8")
        self.assertIn(APPLIED_WEIGHTS_KEY, source)
        self.assertEqual(PLANNING_FX_SESSION_KEY, "wealth_os_2031_usdtry")
        self.assertIn("wealth_os_2031_usdtry", source)
        for token in WRITE_TOKENS:
            self.assertNotIn(token, source)


class PresentationTests(unittest.TestCase):
    def test_turkish_labels_and_statuses(self) -> None:
        self.assertEqual(BUCKET_LABELS["equity"], "Hisse")
        self.assertEqual(BUCKET_LABELS["etf"], "ETF")
        self.assertEqual(BUCKET_LABELS["sukuk"], "Sukuk / Sabit Getirili")
        self.assertEqual(BUCKET_LABELS["cash"], "Nakit")
        self.assertEqual(BUCKET_LABELS["other"], "Diğer")
        view = build_allocation_for_ui(_live_like_view(), session_state=_policy_70_30())
        presented = present_allocation_center(view, draft_weights=_policy_70_30()[APPLIED_WEIGHTS_KEY])
        text = flatten_allocation_text(presented)
        self.assertIn("Hisse", text)
        self.assertIn("ETF", text)
        self.assertIn("Hedef Üstü", text)
        self.assertIn("Hedef Altı", text)
        self.assertNotIn("OVERWEIGHT", text)
        self.assertNotIn("UNDERWEIGHT", text)

    def test_current_vs_target_and_partial_language(self) -> None:
        view = build_allocation_for_ui(_live_like_view(), session_state=_policy_70_30())
        presented = present_allocation_center(view, draft_weights=_policy_70_30()[APPLIED_WEIGHTS_KEY])
        by_id = {row.bucket_id: row for row in presented.rows}
        self.assertAlmostEqual(by_id["equity"].observable_weight_pct or 0, 83.36, places=1)
        self.assertAlmostEqual(by_id["etf"].observable_weight_pct or 0, 16.64, places=1)
        self.assertEqual(by_id["equity"].target_weight_pct, 70.0)
        self.assertEqual(by_id["etf"].target_weight_pct, 30.0)
        text = flatten_allocation_text(presented)
        self.assertIn(PARTIAL_NOTE, text)
        self.assertIn("Kısmi değerleme", text)
        self.assertIn("Ölçülebilir", presented.observable_heading)
        equity = by_id["equity"]
        self.assertIsNotNone(equity.limitation)
        self.assertNotIn("0%", equity.limitation or "")
        self.assertIn("BIMAS", equity.limitation or "")
        self.assertNotEqual(equity.observable_weight_pct, 0)

    def test_unpriced_tr_not_rendered_as_zero(self) -> None:
        view = build_allocation_intelligence(_partial_bist_view())
        presented = present_allocation_center(view)
        equity = next(row for row in presented.rows if row.bucket_id == "equity")
        self.assertIn("BIMAS", " ".join(equity.unpriced_symbols))
        self.assertIsNotNone(equity.limitation)
        self.assertIn("%0 sayılmaz", equity.limitation or "")

    def test_contribution_routing_uses_engine_and_bucket_not_security(self) -> None:
        session = {
            **_policy_70_30(),
            CONTRIB_AMOUNT_KEY: 15,
            "portfolio_allocation_contribution_currency": "USD",
        }
        view = build_allocation_for_ui(_live_like_view(), session_state=session)
        presented = present_allocation_center(view, draft_weights=session[APPLIED_WEIGHTS_KEY])
        self.assertEqual(view.routing[0].best_bucket_id, "etf")
        self.assertEqual(presented.routing.best_bucket_label, "ETF")
        self.assertIn("ETF", presented.routing.message)
        text = flatten_allocation_text(presented).lower()
        self.assertNotIn("spus", text)
        self.assertNotIn("aapl", text)
        self.assertIn(SIMULATION_NOTE.lower(), text)
        self.assertGreater(presented.routing.improvement or 0, 0)

    def test_no_target_and_missing_fx_routing_unavailable(self) -> None:
        empty = present_allocation_center(build_allocation_for_ui(_complete_usd_view(), session_state={}))
        self.assertEqual(empty.routing.message, UNCONFIGURED_ROUTING)
        session = {
            **_policy_70_30(),
            CONTRIB_AMOUNT_KEY: 60000,
            "portfolio_allocation_contribution_currency": "TRY",
        }
        missing_fx = build_allocation_for_ui(_complete_usd_view(), session_state=session)
        presented = present_allocation_center(missing_fx)
        self.assertEqual(presented.routing.message, FX_REQUIRED_COPY)
        session[PLANNING_FX_SESSION_KEY] = 34
        converted = build_allocation_for_ui(_complete_usd_view(), session_state=session)
        self.assertEqual(converted.routing[0].status.value, "AVAILABLE")

    def test_no_buy_sell_language_and_deterministic_tie(self) -> None:
        session = {
            APPLIED_WEIGHTS_KEY: {
                "equity": 50.0,
                "etf": 50.0,
                "sukuk": 0.0,
                "cash": 0.0,
                "other": 0.0,
            },
            CONTRIB_AMOUNT_KEY: 10,
            "portfolio_allocation_contribution_currency": "USD",
        }
        first = build_allocation_for_ui(_complete_usd_view(), session_state=session)
        second = build_allocation_for_ui(_complete_usd_view(), session_state=session)
        self.assertEqual(first.routing[0].best_bucket_id, second.routing[0].best_bucket_id)
        text = flatten_allocation_text(present_allocation_center(first)).lower()
        self.assertNotIn("satın al", text)
        self.assertNotIn("buy spus", text)
        self.assertNotIn("sell aapl", text)
        self.assertIn("al/sat önerisi değildir", text)

    def test_healthy_on_target_state(self) -> None:
        policy = AllocationPolicy(
            targets=(
                AllocationTarget("equity", AllocationDimension.ASSET_CLASS, 40),
                AllocationTarget("etf", AllocationDimension.ASSET_CLASS, 60),
                AllocationTarget("sukuk", AllocationDimension.ASSET_CLASS, 0),
                AllocationTarget("cash", AllocationDimension.ASSET_CLASS, 0),
                AllocationTarget("other", AllocationDimension.ASSET_CLASS, 0),
            ),
            provenance=AllocationProvenance.USER_DEFINED,
        )
        view = build_allocation_intelligence(_complete_usd_view(), policy=policy)
        presented = present_allocation_center(view)
        statuses = {row.status_label for row in presented.rows if row.target_weight_pct}
        self.assertIn("Hedefte", statuses)

    def test_headings(self) -> None:
        presented = present_allocation_center(build_allocation_for_ui(_complete_usd_view(), session_state={}))
        self.assertEqual(presented.heading, HEADING)
        self.assertEqual(presented.routing_heading, ROUTING_HEADING)
        self.assertIn(PLANNED_CONTRIBUTION_LABEL, UI.read_text(encoding="utf-8"))


class SafetyTests(unittest.TestCase):
    def test_no_provider_or_write_path(self) -> None:
        source = UI.read_text(encoding="utf-8").lower()
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token.lower(), source)
        raw = UI.read_text(encoding="utf-8")
        for token in WRITE_TOKENS:
            self.assertNotIn(token, raw)
        self.assertIn("build_allocation_intelligence", raw)
        engine = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("portfolio_allocation_center_ui", engine)

    def test_empty_portfolio_is_safe(self) -> None:
        self.assertIsNone(
            render_portfolio_allocation_center(portfolio_view=_empty_view(), empty_portfolio=True)
        )

    def test_render_shows_heading(self) -> None:
        recorded: list[str] = []

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def number_input(self, *a, **k):
                return 0

            def button(self, *a, **k):
                return False

            def markdown(self, message, **_k):
                recorded.append(str(message))

            def caption(self, message, **_k):
                recorded.append(str(message))

            def info(self, message, **_k):
                recorded.append(str(message))

            def selectbox(self, *a, **k):
                return "USD"

            def altair_chart(self, *a, **k):
                return None

        class _St(_Ctx):
            session_state = {}

            def columns(self, n, **_k):
                count = n if isinstance(n, int) else len(n)
                return [_Ctx() for _ in range(count)]

            def rerun(self):
                return None

        fake = _St()
        with patch.dict("sys.modules", {"streamlit": fake}), patch(
            "components.nabi_design_system._st", return_value=fake
        ):
            presented = render_portfolio_allocation_center(
                allocation=build_allocation_for_ui(_live_like_view(), session_state={}),
                session_state=fake.session_state,
            )
        blob = "\n".join(recorded)
        self.assertIsNotNone(presented)
        self.assertIn(HEADING, blob)
        self.assertIn("Hedef dağılım henüz tanımlanmadı", blob)


if __name__ == "__main__":
    unittest.main()
