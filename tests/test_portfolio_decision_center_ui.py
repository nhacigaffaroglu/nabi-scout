from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.portfolio_decision_center_ui import (
    FX_DIRECTION,
    HEADING,
    MAX_VISIBLE_ACTIONS,
    UNAVAILABLE_MESSAGE,
    build_decision_for_ui,
    flatten_presentation_text,
    present_action_center,
    render_portfolio_decision_center,
)
from services.portfolio_allocation_intelligence import (
    AllocationCompleteness,
    AllocationDecisionSignals,
    AllocationPolicyStatus,
)
from services.portfolio_decision_intelligence import (
    DecisionAction,
    DecisionActionStatus,
    DecisionCategory,
    DecisionPriority,
    PortfolioDecisionView,
    build_portfolio_decision,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_contract import TXN_TYPE_BUY, TXN_TYPE_DEPOSIT
from services.wealth_goal_models import ContributionPlan

AS_OF = date(2026, 8, 18)
ACCOUNT = "acc-1"
UI = Path("components/portfolio_decision_center_ui.py")
PI_PAGE = Path("pages/11_Portfolio_Intelligence.py")
WEALTH_PAGE = Path("pages/10_Wealth.py")
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


def _row(
    *,
    symbol: str,
    price_available: bool,
    market_value,
    currency: str,
    weight_pct=None,
    **kwargs,
) -> PositionValuationRow:
    defaults = dict(
        position_id=f"p-{symbol}",
        account_id=ACCOUNT,
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class="equity",
        account_name="Broker",
        quantity=1,
        average_cost=10,
        valuation_currency=currency,
        price=110 if price_available else None,
        price_available=price_available,
        market_value=market_value,
        cost_basis=10,
        unrealized_pl=100 if price_available else None,
        weight_pct=weight_pct,
        is_cash=False,
        included_in_base_totals=price_available and currency == "USD",
    )
    defaults.update(kwargs)
    return PositionValuationRow(**defaults)


def _view(
    *,
    priced: list[PositionValuationRow],
    unpriced: list[PositionValuationRow] | None = None,
    foreign: list[PositionValuationRow] | None = None,
    mixed: bool = False,
) -> PortfolioIntelligenceView:
    unpriced = unpriced or []
    foreign = foreign or []
    priced_mv = sum(float(row.market_value or 0.0) for row in priced)
    total = len(priced) + len(unpriced) + len(foreign)
    coverage = (len(priced) / total) * 100.0 if total else 100.0
    weights = sorted(
        [float(row.weight_pct or 0.0) for row in priced if row.weight_pct is not None],
        reverse=True,
    )
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=priced_mv,
        priced_total_cost_basis=sum(float(row.cost_basis) for row in priced),
        priced_total_unrealized_pl=sum(float(row.unrealized_pl or 0.0) for row in priced),
        priced_position_count=len(priced),
        unpriced_position_count=len(unpriced) + len(foreign),
        foreign_currency_position_count=len(foreign),
        total_position_count=total,
        mixed_currency_warning=mixed or bool(foreign),
        fx_supported=False,
        priced_positions=priced,
        unpriced_positions=unpriced,
        foreign_currency_positions=foreign,
        asset_class_allocation=[AllocationSlice("equity", "equity", priced_mv, 100.0)],
        account_allocation=[AllocationSlice(ACCOUNT, "Broker", priced_mv, 100.0)],
        health=PortfolioHealthMetrics(
            weights[0] if weights else 0.0,
            sum(weights[:3]),
            100.0,
            0.0,
            100.0,
            coverage,
        ),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


def _partial_bist_view(*, top_weight: float = 19.2) -> PortfolioIntelligenceView:
    priced_mv = 58515.97
    remainder_weight = (100.0 - top_weight) / 5.0
    priced_symbols = (
        ("NVDA", top_weight),
        ("AAPL", remainder_weight),
        ("MSFT", remainder_weight),
        ("AMZN", remainder_weight),
        ("GOOG", remainder_weight),
        ("META", remainder_weight),
    )
    return _view(
        priced=[
            _row(
                symbol=symbol,
                price_available=True,
                market_value=priced_mv * weight / 100.0,
                currency="USD",
                weight_pct=weight,
            )
            for symbol, weight in priced_symbols
        ],
        foreign=[
            _row(symbol="BIMAS", price_available=False, market_value=None, currency="TRY"),
            _row(symbol="ASELS", price_available=False, market_value=None, currency="TRY"),
            _row(symbol="TUPRS", price_available=False, market_value=None, currency="TRY"),
        ],
        mixed=True,
    )


def _empty_view() -> PortfolioIntelligenceView:
    return _view(priced=[])


def _healthy_view() -> PortfolioIntelligenceView:
    weights = (14.0, 14.0, 14.0, 14.0, 14.0, 15.0, 15.0)
    symbols = ("NVDA", "AAPL", "MSFT", "AMZN", "GOOG", "META", "AVGO")
    value = 480000.0
    priced = [
        _row(
            symbol=symbol,
            price_available=True,
            market_value=value * weight / 100.0,
            currency="USD",
            weight_pct=weight,
        )
        for symbol, weight in zip(symbols, weights)
    ]
    return _view(priced=priced)


def _deposit(amount: float) -> dict:
    return {
        "id": f"dep-{amount}",
        "account_id": ACCOUNT,
        "txn_type": TXN_TYPE_DEPOSIT,
        "quantity": 0,
        "amount": amount,
        "currency": "USD",
        "executed_at": "2026-03-01T12:00:00+00:00",
        "created_at": "2026-03-01T12:00:00+00:00",
    }


def _buy(amount: float) -> dict:
    return {
        "id": f"buy-{amount}",
        "account_id": ACCOUNT,
        "txn_type": TXN_TYPE_BUY,
        "quantity": 1,
        "amount": amount,
        "currency": "USD",
        "executed_at": "2026-03-01T12:00:00+00:00",
        "created_at": "2026-03-01T12:00:00+00:00",
    }


def _extra_action(index: int) -> DecisionAction:
    return DecisionAction(
        id=f"extra_{index}",
        category=DecisionCategory.MONITOR,
        priority=DecisionPriority.LOW,
        title=f"Extra {index}",
        explanation="Padding action for visibility cap tests.",
        evidence=(),
        status=DecisionActionStatus.OBSERVE,
    )


def _live_like_decision() -> PortfolioDecisionView:
    return build_portfolio_decision(
        _partial_bist_view(),
        as_of_date=AS_OF,
        transactions=[_buy(1000)],
        account_ids=[ACCOUNT],
    )


class PlacementTests(unittest.TestCase):
    def test_pi_hosts_action_center_after_hero(self) -> None:
        source = PI_PAGE.read_text(encoding="utf-8")
        self.assertIn("render_portfolio_decision_center", source)
        hero = source.index("render_portfolio_executive_hero(")
        center = source.index("render_portfolio_decision_center(")
        overview = source.index("render_portfolio_overview_tab(")
        empty = source.index("render_empty_portfolio_onboarding(")
        self.assertLess(empty, center)
        self.assertLess(hero, center)
        self.assertLess(center, overview)
        self.assertEqual(source.count("render_portfolio_decision_center("), 1)

    def test_wealth_has_reference_not_full_center(self) -> None:
        source = WEALTH_PAGE.read_text(encoding="utf-8")
        self.assertIn("Şimdi neye odaklanmalıyım?", source)
        self.assertIn("Portföy Zekâsı", source)
        self.assertNotIn("render_portfolio_decision_center", source)
        self.assertNotIn("present_action_center", source)


class PresentationTests(unittest.TestCase):
    def test_primary_action_appears_first_in_turkish(self) -> None:
        presented = present_action_center(_live_like_decision())
        self.assertEqual(presented.heading, HEADING)
        self.assertEqual(presented.visible_actions[0].id, "incomplete_valuation")
        self.assertEqual(presented.visible_actions[0].title, "Portföy değerlemesini tamamla")
        self.assertEqual(presented.visible_actions[0].priority_label, "Yüksek")
        self.assertEqual(presented.visible_actions[0].category_label, "Veri")
        self.assertEqual(
            [row.id for row in presented.visible_actions],
            list(presented.action_ids)[: len(presented.visible_actions)],
        )

    def test_priorities_and_categories_translated(self) -> None:
        presented = present_action_center(_live_like_decision())
        text = flatten_presentation_text(presented)
        self.assertIn("Veri", text)
        self.assertIn("Yüksek", text)
        self.assertIn("Orta", text)
        self.assertNotIn("\nDATA\n", f"\n{text}\n")
        self.assertNotIn("\nHIGH\n", f"\n{text}\n")
        self.assertNotIn("\nMEDIUM\n", f"\n{text}\n")
        self.assertNotIn("Complete valuation evidence", text)
        self.assertNotIn("Katkı kanıtı: PARTIAL", text)
        self.assertNotRegex(text, r"\b(HIGH|MEDIUM|DATA|CRITICAL|MONITOR)\b")
        source = UI.read_text(encoding="utf-8")
        self.assertNotIn("BIMAS", source)
        self.assertNotIn("ASELS", source)
        self.assertNotIn("TUPRS", source)

    def test_unresolved_symbols_come_from_engine_evidence(self) -> None:
        presented = present_action_center(_live_like_decision())
        primary = presented.visible_actions[0]
        combined = " ".join(primary.evidence_lines) + " " + primary.explanation
        self.assertIn("BIMAS", combined)
        self.assertIn("ASELS", combined)
        self.assertIn("TUPRS", combined)
        self.assertIn("alt sınır", primary.explanation)

    def test_missing_fx_points_to_planning_assumption(self) -> None:
        presented = present_action_center(_live_like_decision())
        fx = next(row for row in presented.visible_actions if row.id == "missing_planning_fx")
        self.assertEqual(fx.title, "2031 planı için kur varsayımı gerekli")
        self.assertIn("planlama kur varsayımı", fx.explanation)
        self.assertIn("tahmin değildir", fx.explanation)
        self.assertEqual(fx.direction, FX_DIRECTION)
        text = flatten_presentation_text(presented)
        self.assertNotIn("34.00", text)
        self.assertNotIn("kur tahmini", text.lower())

    def test_contribution_does_not_treat_buy_as_deposit(self) -> None:
        presented = present_action_center(_live_like_decision())
        contrib = next(
            row for row in presented.visible_actions if row.id == "contribution_evidence_incomplete"
        )
        self.assertEqual(contrib.title, "Katkı geçmişini tamamla")
        self.assertIn("nakit yatırma", contrib.explanation)
        self.assertIn("yatırma/çekme", contrib.direction or "")
        self.assertEqual(contrib.evidence_lines, ("Katkı kanıtı: kısmi",))
        self.assertNotIn("yatırma olarak sayılır", flatten_presentation_text(presented).lower())

    def test_no_security_trading_recommendation_language(self) -> None:
        presented = present_action_center(_live_like_decision())
        text = flatten_presentation_text(presented).lower()
        self.assertIn("al/sat önerisi üretmez", text)
        self.assertNotIn("satın al", text)
        self.assertNotIn("alım önerisi", text)
        self.assertNotIn("buy nvda", text)
        self.assertNotRegex(text, r"satış önerisi(?! değildir)")
        self.assertNotIn("concentration_review", presented.action_ids)

    def test_partial_valuation_uses_lower_bound_language(self) -> None:
        presented = present_action_center(_live_like_decision())
        text = flatten_presentation_text(presented)
        self.assertIn("Ölçülebilen portföy değeri", text)
        self.assertIn("en az", text)
        self.assertNotIn("Toplam portföyünüz", text)
        self.assertIn("sıfır sayılmaz", text)

    def test_concentration_later_mentions_priced_portion(self) -> None:
        decision = build_portfolio_decision(
            _partial_bist_view(top_weight=40.0),
            as_of_date=AS_OF,
        )
        presented = present_action_center(decision)
        conc = next(row for row in presented.visible_actions if row.id == "concentration_review")
        self.assertIn("fiyatlı / gözlemlenebilir", conc.explanation)
        self.assertIn("satış önerisi değildir", conc.explanation)

    def test_monitor_only_healthy_state(self) -> None:
        decision = build_portfolio_decision(
            _healthy_view(),
            as_of_date=AS_OF,
            plan=ContributionPlan(
                starting_monthly=Decimal("20000"),
                currency="USD",
                annual_increase_rate=Decimal("0"),
            ),
            transactions=[_deposit(20000)],
            account_ids=[ACCOUNT],
        )
        presented = present_action_center(decision)
        self.assertTrue(presented.healthy)
        self.assertIn("öne çıkan bir veri veya planlama açığı görünmüyor", presented.healthy_message or "")
        self.assertEqual(presented.visible_actions[0].id, "continue_observation")
        self.assertEqual(presented.visible_actions[0].title, "İzlemeye devam et")
        self.assertEqual(presented.visible_actions[0].category_label, "İzleme")
        self.assertEqual(presented.visible_actions[0].priority_label, "Bilgi")
        text = flatten_presentation_text(presented)
        self.assertIn("yüksek veya orta öncelikli", text)
        self.assertNotRegex(text, r"\b(HIGH|MEDIUM|DATA|MONITOR)\b")

    def test_max_five_visible_actions_preserve_engine_order(self) -> None:
        base = _live_like_decision()
        extras = tuple(_extra_action(i) for i in range(4))
        padded = PortfolioDecisionView(
            actions=base.actions + extras,
            primary_action=base.primary_action,
            evidence_complete=base.evidence_complete,
            limitations=base.limitations,
            generated_from=base.generated_from,
        )
        presented = present_action_center(padded)
        self.assertEqual(len(padded.actions), 7)
        self.assertEqual(len(presented.visible_actions), MAX_VISIBLE_ACTIONS)
        self.assertEqual(presented.hidden_count, 2)
        self.assertEqual(
            [row.id for row in presented.visible_actions],
            [row.id for row in padded.actions[:MAX_VISIBLE_ACTIONS]],
        )
        self.assertEqual(presented.visible_actions[0].id, padded.primary_action.id)

    def test_evidence_details_render_safely(self) -> None:
        presented = present_action_center(_live_like_decision())
        summary = "\n".join(presented.evidence_summary)
        self.assertTrue(presented.evidence_summary)
        self.assertIn("Değerleme: kısmi", summary)
        self.assertIn("Katkı kanıtı", summary)
        self.assertIn("Performans kanıtı", summary)
        self.assertEqual(summary.count("Performans kanıtı"), 1)
        self.assertEqual(summary.count("Katkı kanıtı"), 1)
        self.assertLessEqual(len(presented.evidence_summary), 5)
        self.assertNotIn("DecisionAction(", summary)
        self.assertNotIn("generated_from", summary)
        self.assertNotIn("{", summary)

    def test_session_fx_does_not_invent_rate_when_absent(self) -> None:
        wealth = MagicMock()
        wealth.list_assets.return_value = []
        wealth.list_positions.return_value = []
        wealth.list_transactions.return_value = [_buy(1000)]
        decision = build_decision_for_ui(
            _partial_bist_view(),
            wealth=wealth,
            accounts=[{"id": ACCOUNT}],
            session_state={},
            as_of=AS_OF,
        )
        self.assertIn("missing_planning_fx", [row.id for row in decision.actions])
        converted = build_decision_for_ui(
            _partial_bist_view(),
            wealth=wealth,
            accounts=[{"id": ACCOUNT}],
            session_state={"wealth_os_2031_usdtry": 34.0},
            as_of=AS_OF,
        )
        self.assertNotIn("missing_planning_fx", [row.id for row in converted.actions])
        wealth.list_transactions.assert_called_with(limit=2000)


def _fake_streamlit(recorded: list[str]):
    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _St:
        session_state = {}

        def caption(self, message, **_k):
            recorded.append(str(message))

        def write(self, message, **_k):
            recorded.append(str(message))

        def markdown(self, message, **_k):
            recorded.append(str(message))

        def success(self, message, **_k):
            recorded.append(str(message))

        def info(self, message, **_k):
            recorded.append(str(message))

        def container(self, **_k):
            return _Ctx()

        def expander(self, label, **_k):
            recorded.append(str(label))
            return _Ctx()

    return _St()


class AllocationActionCenterTests(unittest.TestCase):
    def test_unconfigured_info_is_not_primary_and_has_no_security_language(self) -> None:
        decision = build_portfolio_decision(
            _partial_bist_view(),
            as_of_date=AS_OF,
            transactions=[_buy(1000)],
            account_ids=[ACCOUNT],
            allocation_signals=AllocationDecisionSignals(
                target_status=AllocationPolicyStatus.TARGET_NOT_CONFIGURED,
                completeness=AllocationCompleteness.PARTIAL_ALLOCATION,
                material_drift=False,
                allocation_evidence_incomplete=True,
                contribution_routing_available=False,
                best_routing_bucket_id=None,
                limitations=("TARGET_NOT_CONFIGURED",),
            ),
        )
        presented = present_action_center(decision)
        self.assertEqual(presented.visible_actions[0].id, "incomplete_valuation")
        define = next(
            row for row in presented.visible_actions if row.id == "allocation_target_not_configured"
        )
        self.assertEqual(define.title, "Hedef portföy dağılımını tanımla")
        self.assertEqual(define.priority_label, "Bilgi")
        text = flatten_presentation_text(presented).lower()
        self.assertNotIn("buy spus", text)
        self.assertNotIn("sell aapl", text)

    def test_drift_action_shows_routing_bucket_not_security(self) -> None:
        decision = build_portfolio_decision(
            _partial_bist_view(top_weight=40.0),
            as_of_date=AS_OF,
            transactions=[_buy(1000)],
            account_ids=[ACCOUNT],
            allocation_signals=AllocationDecisionSignals(
                target_status=AllocationPolicyStatus.CONFIGURED,
                completeness=AllocationCompleteness.PARTIAL_ALLOCATION,
                material_drift=True,
                allocation_evidence_incomplete=True,
                contribution_routing_available=True,
                best_routing_bucket_id="etf",
                limitations=("PARTIAL_VALUATION", "OBSERVABLE_ALLOCATION_ONLY"),
            ),
        )
        presented = present_action_center(decision)
        self.assertEqual(presented.visible_actions[0].id, "incomplete_valuation")
        drift = next(row for row in presented.visible_actions if row.id == "allocation_drift_review")
        self.assertEqual(drift.title, "Hedef dağılımdan sapmayı gözden geçir")
        blob = " ".join(drift.evidence_lines).lower() + " " + drift.explanation.lower()
        self.assertIn("etf bölgesine", blob)
        self.assertNotIn("spus", blob)
        self.assertNotIn("satın al", blob)
        self.assertNotIn("sell aapl", blob)

    def test_build_decision_reads_persisted_policy_without_write(self) -> None:
        service = MagicMock()
        service.get_policy.return_value = None
        wealth = MagicMock()
        wealth.list_assets.return_value = []
        wealth.list_positions.return_value = []
        wealth.list_transactions.return_value = [_buy(1000)]
        decision = build_decision_for_ui(
            _partial_bist_view(),
            wealth=wealth,
            accounts=[{"id": ACCOUNT}],
            session_state={},
            as_of=AS_OF,
            policy_service=service,
            portfolio_id="pf-a",
        )
        service.get_policy.assert_called_once_with("pf-a")
        service.save_policy.assert_not_called()
        service.delete_policy.assert_not_called()
        self.assertIn("allocation_target_not_configured", [row.id for row in decision.actions])
        self.assertEqual(decision.primary_action.id, "incomplete_valuation")


class RenderSafetyTests(unittest.TestCase):
    def test_empty_portfolio_is_safe(self) -> None:
        presented = render_portfolio_decision_center(
            portfolio_view=_empty_view(),
            empty_portfolio=True,
            decision=_live_like_decision(),
        )
        self.assertIsNone(presented)
        silent = render_portfolio_decision_center(portfolio_view=_empty_view())
        self.assertIsNone(silent)

    def test_unavailable_state_does_not_invent_actions(self) -> None:
        recorded: list[str] = []
        fake = _fake_streamlit(recorded)
        with patch.dict("sys.modules", {"streamlit": fake}), patch(
            "components.nabi_design_system._st", return_value=fake
        ):
            presented = render_portfolio_decision_center()
        self.assertIsNone(presented)
        self.assertTrue(any(UNAVAILABLE_MESSAGE in item for item in recorded))

    def test_render_shows_heading_and_primary(self) -> None:
        recorded: list[str] = []
        fake = _fake_streamlit(recorded)
        with patch.dict("sys.modules", {"streamlit": fake}), patch(
            "components.nabi_design_system._st", return_value=fake
        ):
            presented = render_portfolio_decision_center(decision=_live_like_decision())
        blob = "\n".join(recorded)
        self.assertIsNotNone(presented)
        self.assertIn(HEADING, blob)
        self.assertIn("Portföy değerlemesini tamamla", blob)
        self.assertIn("Bu öneriler neye dayanıyor?", blob)
        self.assertIn("BIMAS", blob)

    def test_no_provider_or_write_path(self) -> None:
        source = UI.read_text(encoding="utf-8")
        lower = source.lower()
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token.lower(), lower)
        for token in WRITE_TOKENS:
            self.assertNotIn(token, source)
        self.assertNotIn("switch_page", source)
        self.assertIn("build_portfolio_decision", source)


if __name__ == "__main__":
    unittest.main()
