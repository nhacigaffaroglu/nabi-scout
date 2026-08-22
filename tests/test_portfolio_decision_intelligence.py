from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from services.portfolio_allocation_intelligence import (
    AllocationCompleteness,
    AllocationDecisionSignals,
    AllocationPolicyStatus,
)
from services.portfolio_decision_intelligence import (
    CONCENTRATION_REVIEW_THRESHOLD_PCT,
    DecisionActionStatus,
    DecisionCategory,
    DecisionPriority,
    build_portfolio_decision,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_contract import TXN_TYPE_BUY, TXN_TYPE_DEPOSIT
from services.wealth_contribution_intelligence import (
    ContributionEvidenceQuality,
    PerformanceEvidenceQuality,
    PlanAdequacyStatus,
)
from services.wealth_goal_models import (
    ContributionPlan,
    ConversionAssumption,
    WealthGoal,
    current_wealth_from_portfolio_view,
    default_contribution_plan,
    default_wealth_goal_2031,
)
from services.wealth_goal_planning import solve_required_starting_monthly
from services.wealth_external_cash_flow import ContributionReconciliation
from services.wealth_history_service import (
    HistoryAttributionStatus,
    WealthHistoryState,
    WealthHistoryView,
)

AS_OF = date(2026, 8, 18)
ACCOUNT = "acc-1"


def _recon(through: date = AS_OF):
    return (ContributionReconciliation(portfolio_id="pf-1", reconciled_through=through),)
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
ENGINE = Path("services/portfolio_decision_intelligence.py")


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


def _partial_bist_view(*, top_weight: float = 15.0) -> PortfolioIntelligenceView:
    priced_mv = 58642.17
    return _view(
        priced=[
            _row(
                symbol="NVDA",
                price_available=True,
                market_value=priced_mv * top_weight / 100.0,
                currency="USD",
                weight_pct=top_weight,
            ),
            _row(
                symbol="AAPL",
                price_available=True,
                market_value=priced_mv * (100.0 - top_weight) / 100.0,
                currency="USD",
                weight_pct=100.0 - top_weight,
            ),
        ],
        foreign=[
            _row(symbol="BIMAS", price_available=False, market_value=None, currency="TRY"),
            _row(symbol="ASELS", price_available=False, market_value=None, currency="TRY"),
            _row(symbol="TUPRS", price_available=False, market_value=None, currency="TRY"),
        ],
        mixed=True,
    )


def _complete_usd_view(*, top_weight: float = 15.0, value: float = 50000.0) -> PortfolioIntelligenceView:
    remainder = 100.0 - top_weight
    return _view(
        priced=[
            _row(
                symbol="NVDA",
                price_available=True,
                market_value=value * top_weight / 100.0,
                currency="USD",
                weight_pct=top_weight,
            ),
            _row(
                symbol="AAPL",
                price_available=True,
                market_value=value * remainder / 100.0,
                currency="USD",
                weight_pct=remainder,
            ),
        ]
    )


def _diversified_usd_view(*, value: float = 480000.0) -> PortfolioIntelligenceView:
    weights = (14.0, 14.0, 14.0, 14.0, 14.0, 15.0, 15.0)
    symbols = ("NVDA", "AAPL", "MSFT", "AMZN", "GOOG", "META", "AVGO")
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


def _buy(amount: float = 1000.0) -> dict:
    return {
        "id": "buy-1",
        "account_id": ACCOUNT,
        "txn_type": TXN_TYPE_BUY,
        "amount": amount,
        "currency": "USD",
        "executed_at": "2026-08-10T12:00:00+00:00",
        "quantity": 1,
    }


def _deposit(amount: float = 1000.0) -> dict:
    return {
        "id": "dep-1",
        "account_id": ACCOUNT,
        "txn_type": TXN_TYPE_DEPOSIT,
        "amount": amount,
        "currency": "USD",
        "executed_at": "2026-08-10T12:00:00+00:00",
        "quantity": 0,
    }


def _history_unavailable() -> WealthHistoryView:
    return WealthHistoryView(
        snapshot_count=2,
        history_state=WealthHistoryState.STARTED,
        period_start="2026-08-17T06:30:00+00:00",
        period_end="2026-08-18T06:30:00+00:00",
        start_value=Decimal("58642.17"),
        end_value=Decimal("58515.97"),
        net_external_contributions=None,
        investment_gain_loss=None,
        return_pct=None,
        valuation_complete_start=False,
        valuation_complete_end=False,
        evidence_quality=PerformanceEvidenceQuality.PARTIAL,
        contribution_evidence_quality=ContributionEvidenceQuality.PARTIAL,
        attribution_status=HistoryAttributionStatus.EVIDENCE_INCOMPLETE,
        attribution_summary="incomplete",
        limitations=("PARTIAL_VALUATION",),
        curve_points=(),
        bridge_available=False,
        latest_snapshot_at="2026-08-18T06:30:00+00:00",
        latest_value=Decimal("58515.97"),
        latest_is_partial=True,
        currency="USD",
        summary="started",
    )


def _ids(view) -> set[str]:
    return {row.id for row in view.actions}


def _text(view) -> str:
    parts = [view.primary_action.title, view.primary_action.explanation]
    for row in view.actions:
        parts.extend([row.title, row.explanation])
    return " ".join(parts).lower()


class PartialValuationTests(unittest.TestCase):
    def test_bist_unpriced_data_action_preserves_symbols(self) -> None:
        view = build_portfolio_decision(_partial_bist_view(), as_of_date=AS_OF)
        action = next(row for row in view.actions if row.id == "incomplete_valuation")
        self.assertEqual(action.category, DecisionCategory.DATA)
        self.assertEqual(action.priority, DecisionPriority.HIGH)
        self.assertEqual(
            set(action.context["unvalued_symbols"]),
            {"BIMAS", "ASELS", "TUPRS"},
        )
        self.assertIn("lower bound", action.explanation.lower())
        self.assertNotIn("worthless", action.explanation.lower())


class PlanningFxTests(unittest.TestCase):
    def test_missing_planning_fx_blocks_projection(self) -> None:
        view = build_portfolio_decision(
            _complete_usd_view(),
            as_of_date=AS_OF,
            plan=default_contribution_plan(),
            conversion=None,
        )
        action = next(row for row in view.actions if row.id == "missing_planning_fx")
        self.assertEqual(action.category, DecisionCategory.DATA)
        self.assertIn("planning FX", action.explanation)
        self.assertFalse(action.context["conversion_present"])
        self.assertNotIn("contribution_plan_below_required", _ids(view))


class ContributionEvidenceTests(unittest.TestCase):
    def test_buy_only_history_is_not_actual_zero(self) -> None:
        view = build_portfolio_decision(
            _complete_usd_view(),
            as_of_date=AS_OF,
            transactions=[_buy()],
            account_ids=[ACCOUNT],
            plan=ContributionPlan(
                starting_monthly=Decimal("1000"),
                currency="USD",
                annual_increase_rate=Decimal("0"),
            ),
            contribution_tracking_start=date(2026, 1, 1),
        )
        action = next(row for row in view.actions if row.id == "contribution_evidence_incomplete")
        self.assertEqual(action.category, DecisionCategory.DATA)
        self.assertIsNone(action.context["actual_monthly_net_contribution"])
        self.assertIsNone(action.context["monthly_remaining"])
        self.assertFalse(action.context["actual_is_zero"])
        self.assertIn("not deposits", action.explanation.lower())


class GoalPlanTests(unittest.TestCase):
    def test_incomplete_evidence_cannot_become_below_required(self) -> None:
        view = build_portfolio_decision(
            _partial_bist_view(),
            as_of_date=AS_OF,
            conversion=ConversionAssumption("TRY", "USD", Decimal("34")),
        )
        self.assertNotIn("contribution_plan_below_required", _ids(view))
        statuses = [
            row.context.get("plan_adequacy_status")
            for row in view.actions
            if "plan_adequacy_status" in row.context
        ]
        self.assertNotIn(PlanAdequacyStatus.BELOW_REQUIRED.value, statuses)

    def test_complete_projection_insufficient_plan(self) -> None:
        portfolio = _complete_usd_view(value=10000.0)
        current = current_wealth_from_portfolio_view(portfolio)
        conversion = ConversionAssumption("TRY", "USD", Decimal("34"))
        required = solve_required_starting_monthly(
            as_of_date=AS_OF,
            current=current,
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0.25"),
            annual_return_rate=Decimal("0.08"),
            conversion=conversion,
        )
        self.assertTrue(required.available)
        self.assertIsNotNone(required.starting_monthly)
        plan = ContributionPlan(
            starting_monthly=max(Decimal("1"), required.starting_monthly - Decimal("5000")),
            currency="TRY",
            annual_increase_rate=Decimal("0.25"),
        )
        view = build_portfolio_decision(
            portfolio,
            as_of_date=AS_OF,
            plan=plan,
            conversion=conversion,
            transactions=[_deposit(50000)],
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon(),
        )
        self.assertIn("contribution_plan_below_required", _ids(view))
        action = next(row for row in view.actions if row.id == "contribution_plan_below_required")
        self.assertEqual(action.category, DecisionCategory.PLAN)
        self.assertEqual(action.priority, DecisionPriority.HIGH)

    def test_complete_projection_sufficient_plan_no_shortfall(self) -> None:
        portfolio = _complete_usd_view(value=10000.0)
        current = current_wealth_from_portfolio_view(portfolio)
        conversion = ConversionAssumption("TRY", "USD", Decimal("34"))
        required = solve_required_starting_monthly(
            as_of_date=AS_OF,
            current=current,
            contribution_currency="TRY",
            annual_increase_rate=Decimal("0.25"),
            annual_return_rate=Decimal("0.08"),
            conversion=conversion,
        )
        plan = ContributionPlan(
            starting_monthly=(required.starting_monthly or Decimal("0")) + Decimal("5000"),
            currency="TRY",
            annual_increase_rate=Decimal("0.25"),
        )
        view = build_portfolio_decision(
            portfolio,
            as_of_date=AS_OF,
            plan=plan,
            conversion=conversion,
            transactions=[_deposit(50000)],
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon(),
        )
        self.assertNotIn("contribution_plan_below_required", _ids(view))


class ConcentrationTests(unittest.TestCase):
    def test_concentration_is_review_not_sell(self) -> None:
        view = build_portfolio_decision(
            _complete_usd_view(top_weight=30.0),
            as_of_date=AS_OF,
            plan=ContributionPlan(
                starting_monthly=Decimal("1000"),
                currency="USD",
            ),
            conversion=None,
            transactions=[_deposit(50000)],
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon(),
        )
        action = next(row for row in view.actions if row.id == "concentration_review")
        self.assertEqual(action.category, DecisionCategory.PORTFOLIO)
        self.assertGreaterEqual(action.context["weight_pct"], CONCENTRATION_REVIEW_THRESHOLD_PCT)
        combined = _text(view)
        self.assertIn("review concentration", combined)
        self.assertNotIn("sell nvda", combined)
        self.assertNotIn("buy nvda", combined)

    def test_partial_valuation_concentration_has_limitation(self) -> None:
        view = build_portfolio_decision(
            _partial_bist_view(top_weight=40.0),
            as_of_date=AS_OF,
        )
        action = next(row for row in view.actions if row.id == "concentration_review")
        self.assertIn("PARTIAL_VALUATION", action.limitations)
        self.assertIn("WEIGHTS_USE_PRICED_MV_ONLY", action.limitations)
        self.assertTrue(action.context["partial_valuation"])


class PerformanceAndFallbackTests(unittest.TestCase):
    def test_unavailable_performance_does_not_fabricate_return(self) -> None:
        view = build_portfolio_decision(
            _partial_bist_view(),
            as_of_date=AS_OF,
            history=_history_unavailable(),
        )
        self.assertIn("PERFORMANCE_EVIDENCE_INCOMPLETE", view.limitations)
        self.assertNotIn("performance_evidence_unavailable", _ids(view))
        self.assertIsNone(getattr(view, "return_pct", None))
        combined = _text(view)
        self.assertNotIn("modified dietz", combined)
        self.assertNotIn("period return", combined)

    def test_healthy_complete_state_monitor_fallback(self) -> None:
        portfolio = _diversified_usd_view()
        view = build_portfolio_decision(
            portfolio,
            as_of_date=AS_OF,
            goal=WealthGoal(name="Near", target_amount=Decimal("500000"), target_date=date(2031, 12, 31)),
            plan=ContributionPlan(
                starting_monthly=Decimal("20000"),
                currency="USD",
                annual_increase_rate=Decimal("0"),
            ),
            transactions=[_deposit(20000)],
            account_ids=[ACCOUNT],
            contribution_reconciliations=_recon(),
            contribution_tracking_start=date(2026, 1, 1),
        )
        self.assertIn("continue_observation", _ids(view))
        self.assertNotIn("incomplete_valuation", _ids(view))
        self.assertNotIn("missing_planning_fx", _ids(view))
        self.assertNotIn("contribution_plan_below_required", _ids(view))
        self.assertEqual(view.primary_action.category, DecisionCategory.MONITOR)

    def test_primary_action_is_deterministic(self) -> None:
        first = build_portfolio_decision(_partial_bist_view(top_weight=40.0), as_of_date=AS_OF)
        second = build_portfolio_decision(_partial_bist_view(top_weight=40.0), as_of_date=AS_OF)
        self.assertEqual(first.primary_action.id, second.primary_action.id)
        self.assertEqual([row.id for row in first.actions], [row.id for row in second.actions])
        self.assertEqual(first.primary_action.id, first.actions[0].id)
        self.assertEqual(first.primary_action.category, DecisionCategory.DATA)
        self.assertEqual(first.primary_action.priority, DecisionPriority.HIGH)


def _signals(
    *,
    configured: bool,
    material_drift: bool = False,
    routing_bucket: str | None = None,
    incomplete: bool = True,
    limitations: tuple[str, ...] | None = None,
    unknown_exposure_symbols: tuple[str, ...] = (),
) -> AllocationDecisionSignals:
    notes = ("PARTIAL_VALUATION",) if incomplete else ()
    if limitations is not None:
        notes = limitations
    return AllocationDecisionSignals(
        target_status=(
            AllocationPolicyStatus.CONFIGURED
            if configured
            else AllocationPolicyStatus.TARGET_NOT_CONFIGURED
        ),
        completeness=(
            AllocationCompleteness.PARTIAL_ALLOCATION
            if incomplete
            else AllocationCompleteness.COMPLETE_ALLOCATION
        ),
        material_drift=material_drift,
        allocation_evidence_incomplete=incomplete,
        contribution_routing_available=bool(routing_bucket),
        best_routing_bucket_id=routing_bucket,
        limitations=notes,
        unknown_exposure_symbols=unknown_exposure_symbols,
    )


class AllocationSignalIntegrationTests(unittest.TestCase):
    def test_unconfigured_does_not_fabricate_drift(self) -> None:
        view = build_portfolio_decision(
            _partial_bist_view(),
            as_of_date=AS_OF,
            allocation_signals=_signals(configured=False),
        )
        self.assertNotIn("allocation_drift_review", _ids(view))
        self.assertIn("allocation_target_not_configured", _ids(view))
        self.assertEqual(view.primary_action.id, "incomplete_valuation")
        self.assertEqual(view.primary_action.priority, DecisionPriority.HIGH)

    def test_incomplete_drift_does_not_create_false_action(self) -> None:
        view = build_portfolio_decision(
            _partial_bist_view(),
            as_of_date=AS_OF,
            allocation_signals=_signals(configured=True, material_drift=False),
        )
        self.assertNotIn("allocation_drift_review", _ids(view))
        self.assertNotIn("allocation_target_not_configured", _ids(view))

    def test_material_drift_is_portfolio_medium_and_not_primary_over_data(self) -> None:
        view = build_portfolio_decision(
            _partial_bist_view(top_weight=40.0),
            as_of_date=AS_OF,
            allocation_signals=_signals(
                configured=True,
                material_drift=True,
                routing_bucket="etf",
            ),
        )
        action = next(row for row in view.actions if row.id == "allocation_drift_review")
        self.assertEqual(action.category, DecisionCategory.PORTFOLIO)
        self.assertEqual(action.priority, DecisionPriority.MEDIUM)
        self.assertEqual(action.status, DecisionActionStatus.INDETERMINATE)
        self.assertEqual(view.primary_action.id, "incomplete_valuation")
        self.assertEqual(view.primary_action.priority, DecisionPriority.HIGH)
        self.assertIn("etf bölgesine", " ".join(action.evidence).lower())
        combined = _text(view)
        self.assertNotIn("buy spus", combined)
        self.assertNotIn("sell aapl", combined)
        self.assertNotIn("aapl", " ".join(action.evidence).lower())

    def test_no_signals_keeps_existing_priority(self) -> None:
        view = build_portfolio_decision(_partial_bist_view(), as_of_date=AS_OF)
        self.assertNotIn("allocation_drift_review", _ids(view))
        self.assertNotIn("allocation_target_not_configured", _ids(view))
        self.assertEqual(view.primary_action.id, "incomplete_valuation")

    def test_configured_target_removes_missing_action_and_adds_exposure_data(self) -> None:
        view = build_portfolio_decision(
            _partial_bist_view(),
            as_of_date=AS_OF,
            allocation_signals=_signals(
                configured=True,
                material_drift=True,
                limitations=("PARTIAL_VALUATION", "EXPOSURE_CLASSIFICATION_INCOMPLETE"),
                unknown_exposure_symbols=("SPUS", "SPSK", "SPRE", "SPWO"),
            ),
        )
        self.assertNotIn("allocation_target_not_configured", _ids(view))
        action = next(row for row in view.actions if row.id == "economic_exposure_incomplete")
        self.assertEqual(action.category, DecisionCategory.DATA)
        self.assertEqual(action.priority, DecisionPriority.MEDIUM)
        self.assertEqual(action.title, "Ekonomik maruziyet sınıflandırmasını tamamla")
        self.assertIn("SPUS", " ".join(action.evidence))
        self.assertNotIn("equity", " ".join(action.evidence).lower())
        self.assertEqual(view.primary_action.id, "incomplete_valuation")
        self.assertEqual(view.primary_action.priority, DecisionPriority.HIGH)
        combined = _text(view)
        self.assertNotIn("buy spus", combined)
        self.assertNotIn("sell aapl", combined)


class SafetyTests(unittest.TestCase):
    def test_no_provider_calls(self) -> None:
        source = ENGINE.read_text(encoding="utf-8").lower()
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token.lower(), source)
        build_portfolio_decision(_partial_bist_view(), as_of_date=AS_OF)

    def test_no_persistence_or_trade_language(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        for token in WRITE_TOKENS:
            self.assertNotIn(token, source)
        view = build_portfolio_decision(_partial_bist_view(top_weight=40.0), as_of_date=AS_OF)
        combined = _text(view)
        self.assertNotIn("buy nvda", combined)
        self.assertNotIn("sell nvda", combined)
        self.assertNotIn("you should invest", combined)


if __name__ == "__main__":
    unittest.main()
