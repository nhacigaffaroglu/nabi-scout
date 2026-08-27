from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    AllocationPolicy,
    AllocationProvenance,
    AllocationTarget,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_goal_models import ConversionAssumption
from services.wealth_new_money_allocation import (
    ACTIONABLE_NEW_DECISIONS,
    REASON_BELOW_MIN_TRADE,
    REASON_CONCENTRATION_LIMIT,
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_FX_REQUIRED,
    REASON_INSUFFICIENT_CASH,
    REASON_MIX_MAINTENANCE,
    REASON_NOT_ACTIONABLE,
    REASON_OVERWEIGHT_LAYER,
    REASON_PARTICIPATION_BLOCKED,
    REASON_STRONG_CANDIDATE,
    allocate_new_money,
    is_actionable_new_decision,
)

ENGINE = Path("services/wealth_new_money_allocation.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "TwelveData",
    "BorsaIstanbul",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    ".update(",
    "capture_portfolio_snapshot",
)


def _row(
    symbol: str,
    *,
    market_value: float,
    weight_pct: float,
    asset_class: str = "equity",
    price: float = 100.0,
    currency: str = "USD",
    price_available: bool = True,
    participation: str | None = "Uygun",
) -> PositionValuationRow:
    nabi = (
        None
        if participation is None
        else SimpleNamespace(participation_status=participation, symbol=symbol)
    )
    return PositionValuationRow(
        position_id=f"p-{symbol}",
        account_id="acc-1",
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class=asset_class,
        account_name="Broker",
        quantity=market_value / price if price else 0,
        average_cost=price,
        valuation_currency=currency,
        price=price if price_available else None,
        price_available=price_available,
        market_value=market_value if price_available else None,
        cost_basis=market_value,
        unrealized_pl=0,
        weight_pct=weight_pct,
        is_cash=asset_class == "cash",
        included_in_base_totals=price_available and currency == "USD",
        nabi=nabi,
    )


def _view(priced: list[PositionValuationRow]) -> PortfolioIntelligenceView:
    priced_mv = sum(float(row.market_value or 0.0) for row in priced)
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=priced_mv,
        priced_total_cost_basis=priced_mv,
        priced_total_unrealized_pl=0.0,
        priced_position_count=len(priced),
        unpriced_position_count=0,
        foreign_currency_position_count=0,
        total_position_count=len(priced),
        mixed_currency_warning=False,
        fx_supported=False,
        priced_positions=tuple(priced),
        unpriced_positions=(),
        foreign_currency_positions=(),
        asset_class_allocation=[AllocationSlice("equity", "equity", priced_mv, 100.0)],
        account_allocation=[AllocationSlice("acc-1", "Broker", priced_mv, 100.0)],
        health=PortfolioHealthMetrics(100.0, 100.0, 100.0, 0.0, 100.0, 100.0),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


def _policy(*, equity: float, etf: float, cash: float = 0.0) -> AllocationPolicy:
    return AllocationPolicy(
        targets=(
            AllocationTarget("equity", AllocationDimension.ASSET_CLASS, equity),
            AllocationTarget("etf", AllocationDimension.ASSET_CLASS, etf),
            AllocationTarget("cash", AllocationDimension.ASSET_CLASS, cash),
        ),
        provenance=AllocationProvenance.USER_DEFINED,
    )


def _fx(rate: str = "30") -> ConversionAssumption:
    return ConversionAssumption("TRY", "USD", Decimal(rate))


def _candidate(symbol: str, decision, price=100, **extra) -> dict:
    row = {
        "symbol": symbol,
        "decision": decision,
        "current_price": price,
        "currency": "USD",
        "market": "US",
        "asset_type": "Hisse",
        "participation_status": "Uygun",
        "data_source": extra.pop("data_source", "FMP"),
    }
    row.update(extra)
    return row


def _plan(*, view=None, policy=None, candidates=(), amount="60000", min_trade="0", conversion=...):
    return allocate_new_money(
        available_amount=Decimal(amount),
        amount_currency="TRY",
        portfolio_view=view or _view([_row("AAPL", market_value=10000, weight_pct=100, price=100)]),
        policy=policy or _policy(equity=40, etf=60),
        candidates=candidates,
        conversion=_fx() if conversion is ... else conversion,
        minimum_trade_amount=Decimal(min_trade),
    )


class EligibilityTests(unittest.TestCase):
    def test_actionable_pool_is_strong_and_aday(self) -> None:
        self.assertEqual(ACTIONABLE_NEW_DECISIONS, frozenset({"GÜÇLÜ ADAY", "ADAY"}))
        self.assertTrue(is_actionable_new_decision("GÜÇLÜ ADAY"))
        self.assertTrue(is_actionable_new_decision("ADAY"))

    def test_izle_excluded(self) -> None:
        plan = _plan(candidates=[_candidate("WATCH", "İZLE", asset_type="ETF")])
        self.assertTrue(any(row.reason_code == REASON_NOT_ACTIONABLE and row.symbol == "WATCH" for row in plan.skipped))
        self.assertNotIn("WATCH", [row.symbol for row in plan.recommendations])

    def test_arastir_excluded(self) -> None:
        plan = _plan(candidates=[_candidate("RESEARCH", "ARAŞTIR", asset_type="ETF")])
        self.assertTrue(any(row.symbol == "RESEARCH" and row.reason_code == REASON_NOT_ACTIONABLE for row in plan.skipped))

    def test_veri_eksik_excluded(self) -> None:
        plan = _plan(candidates=[_candidate("THIN", "VERİ EKSİK", asset_type="ETF")])
        self.assertTrue(any(row.symbol == "THIN" and row.reason_code == REASON_NOT_ACTIONABLE for row in plan.skipped))

    def test_null_decision_excluded(self) -> None:
        plan = _plan(candidates=[_candidate("BLANK", None, asset_type="ETF")])
        self.assertTrue(any(row.symbol == "BLANK" and row.reason_code == REASON_NOT_ACTIONABLE for row in plan.skipped))

    def test_valuation_only_bist_row_not_auto_eligible(self) -> None:
        plan = _plan(
            candidates=[
                _candidate(
                    "TUPRS",
                    None,
                    price=200,
                    market="TR",
                    currency="TRY",
                    data_source="BORSA_ISTANBUL_EOD",
                    asset_type="Hisse",
                )
            ]
        )
        self.assertTrue(
            any(row.symbol == "TUPRS" and row.reason_code == REASON_NOT_ACTIONABLE for row in plan.skipped)
        )
        self.assertNotIn("TUPRS", [row.symbol for row in plan.recommendations])


class HoldingAndLayerTests(unittest.TestCase):
    def test_existing_holding_can_top_up_without_aday(self) -> None:
        view = _view(
            [
                _row("AAPL", market_value=1000, weight_pct=10, price=100),
                _row("SPUS", market_value=9000, weight_pct=90, price=100, asset_class="etf"),
            ]
        )
        plan = _plan(view=view, policy=_policy(equity=40, etf=60), candidates=[])
        symbols = [row.symbol for row in plan.recommendations]
        self.assertIn("AAPL", symbols)
        aapl = next(row for row in plan.recommendations if row.symbol == "AAPL")
        self.assertEqual(aapl.existing_or_new, "existing")
        self.assertEqual(aapl.reason_code, REASON_EXISTING_HOLDING_TOPUP)
        self.assertGreater(aapl.quantity, 0)

    def test_overweight_layer_gets_no_default_allocation(self) -> None:
        view = _view([_row("AAPL", market_value=10000, weight_pct=100, price=100)])
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
        )
        self.assertTrue(any(row.symbol == "AAPL" and row.reason_code == REASON_OVERWEIGHT_LAYER for row in plan.skipped))
        self.assertNotIn("AAPL", [row.symbol for row in plan.recommendations])
        self.assertNotIn("MSFT", [row.symbol for row in plan.recommendations])

    def test_underweight_layer_is_prioritized(self) -> None:
        view = _view([_row("AAPL", market_value=10000, weight_pct=100, price=100)])
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[_candidate("SPUS", "ADAY", asset_type="ETF")],
        )
        self.assertEqual([row.symbol for row in plan.recommendations], ["SPUS"])
        self.assertEqual(plan.recommendations[0].layer, "etf")


class SizingTests(unittest.TestCase):
    def test_whole_share_rounding(self) -> None:
        plan = _plan(
            view=_view([_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "ADAY", price=100)],
            amount="5000",
        )
        rec = next(row for row in plan.recommendations if row.symbol == "MSFT")
        self.assertEqual(rec.quantity, rec.quantity.to_integral_value())
        self.assertLessEqual(rec.allocated_amount, Decimal("5000"))

    def test_insufficient_cash_leaves_residual(self) -> None:
        plan = _plan(
            view=_view([_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "ADAY", price=100)],
            amount="2000",
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.residual_cash, Decimal("2000"))
        self.assertTrue(any(row.reason_code == REASON_INSUFFICIENT_CASH for row in plan.skipped))

    def test_minimum_efficient_trade_respected(self) -> None:
        plan = _plan(
            view=_view([_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "ADAY", price=100)],
            amount="60000",
            min_trade="100000",
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.residual_cash, Decimal("60000"))
        self.assertTrue(any(row.reason_code == REASON_BELOW_MIN_TRADE for row in plan.skipped))

    def test_invalid_price_skipped(self) -> None:
        plan = _plan(
            view=_view([_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY", price=0)],
        )
        self.assertTrue(any(row.symbol == "MSFT" and row.reason_code == REASON_NOT_ACTIONABLE for row in plan.skipped))
        self.assertNotIn("MSFT", [row.symbol for row in plan.recommendations])

    def test_strong_candidate_ranks_ahead_of_aday(self) -> None:
        plan = _plan(
            view=_view([_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]),
            policy=_policy(equity=80, etf=20),
            candidates=[
                _candidate("AAA", "ADAY", price=100),
                _candidate("ZZZ", "GÜÇLÜ ADAY", price=100),
            ],
            amount="6000",
        )
        self.assertTrue(plan.recommendations)
        self.assertEqual(plan.recommendations[0].symbol, "ZZZ")
        self.assertEqual(plan.recommendations[0].reason_code, REASON_STRONG_CANDIDATE)
        self.assertNotIn("AAA", [row.symbol for row in plan.recommendations])

    def test_total_allocated_never_exceeds_input(self) -> None:
        plan = _plan(
            view=_view([_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]),
            policy=_policy(equity=80, etf=20),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY", price=100)],
            amount="60000",
        )
        self.assertLessEqual(plan.total_allocated, plan.input_amount)
        self.assertEqual(plan.total_allocated + plan.residual_cash, plan.input_amount)

    def test_identical_inputs_are_deterministic(self) -> None:
        kwargs = dict(
            view=_view([_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]),
            policy=_policy(equity=80, etf=20),
            candidates=[
                _candidate("MSFT", "GÜÇLÜ ADAY", price=100),
                _candidate("AAPL", "ADAY", price=80),
            ],
            amount="60000",
        )
        first = _plan(**kwargs)
        second = _plan(**kwargs)
        self.assertEqual(first, second)


def _on_target_book():
    return _view(
        [
            _row("AAPL", market_value=1400, weight_pct=14, price=100),
            _row("MSFT", market_value=1400, weight_pct=14, price=100),
            _row("NVDA", market_value=1400, weight_pct=14, price=100),
            _row("GOOG", market_value=1400, weight_pct=14, price=100),
            _row("AMZN", market_value=1400, weight_pct=14, price=100),
            _row("SPUS", market_value=1500, weight_pct=15, price=100, asset_class="etf"),
            _row("HLAL", market_value=1500, weight_pct=15, price=100, asset_class="etf"),
        ]
    )


class NewMoneyEngineV2Tests(unittest.TestCase):
    def test_a_underweight_existing_uygun_topup(self) -> None:
        view = _view(
            [
                _row("AAPL", market_value=1000, weight_pct=10, price=100),
                _row("SPUS", market_value=9000, weight_pct=90, price=100, asset_class="etf"),
            ]
        )
        plan = _plan(view=view, policy=_policy(equity=40, etf=60), candidates=[], amount="100000")
        rec = next(row for row in plan.recommendations if row.symbol == "AAPL")
        self.assertEqual(rec.existing_or_new, "existing")
        self.assertEqual(rec.reason_code, REASON_EXISTING_HOLDING_TOPUP)
        self.assertGreater(rec.allocated_amount, 0)
        self.assertLess(plan.residual_cash, plan.input_amount)

    def test_b_underweight_new_strong_candidate(self) -> None:
        view = _view(
            [_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("CRM", "GÜÇLÜ ADAY")],
            amount="100000",
        )
        rec = next(row for row in plan.recommendations if row.symbol == "CRM")
        self.assertEqual(rec.existing_or_new, "new")
        self.assertEqual(rec.reason_code, REASON_STRONG_CANDIDATE)
        self.assertGreater(rec.allocated_amount, 0)

    def test_c_kontrol_et_candidate_is_blocked(self) -> None:
        view = _view(
            [_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("FOO", "GÜÇLÜ ADAY", participation_status="Kontrol Et")],
            amount="100000",
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertTrue(
            any(row.symbol == "FOO" and row.reason_code == REASON_PARTICIPATION_BLOCKED for row in plan.skipped)
        )

    def test_d_uygun_degil_holding_is_not_topped_up(self) -> None:
        view = _view(
            [
                _row(
                    "AAPL",
                    market_value=1000,
                    weight_pct=10,
                    price=100,
                    participation="Uygun Değil",
                ),
                _row("SPUS", market_value=9000, weight_pct=90, price=100, asset_class="etf"),
            ]
        )
        plan = _plan(view=view, policy=_policy(equity=40, etf=60), candidates=[], amount="100000")
        self.assertNotIn("AAPL", [row.symbol for row in plan.recommendations])
        self.assertTrue(
            any(row.symbol == "AAPL" and row.reason_code == REASON_PARTICIPATION_BLOCKED for row in plan.skipped)
        )
        self.assertEqual(plan.residual_cash, Decimal("100000"))

    def test_e_on_target_mix_is_not_forced_cash(self) -> None:
        plan = _plan(
            view=_on_target_book(),
            policy=_policy(equity=70, etf=30),
            candidates=[],
            amount="100000",
        )
        self.assertTrue(plan.recommendations)
        layers = {row.layer for row in plan.recommendations}
        self.assertIn("equity", layers)
        self.assertIn("etf", layers)
        self.assertGreater(plan.total_allocated, 0)
        self.assertLess(plan.residual_cash, plan.input_amount)
        self.assertTrue(all(row.reason_code == REASON_MIX_MAINTENANCE for row in plan.recommendations))

    def test_f_on_target_one_eligible_sleeve_keeps_residual(self) -> None:
        view = _view(
            [
                _row("AAPL", market_value=1400, weight_pct=14, price=100, participation="Uygun Değil"),
                _row("MSFT", market_value=1400, weight_pct=14, price=100, participation="Uygun Değil"),
                _row("NVDA", market_value=1400, weight_pct=14, price=100, participation="Uygun Değil"),
                _row("GOOG", market_value=1400, weight_pct=14, price=100, participation="Uygun Değil"),
                _row("AMZN", market_value=1400, weight_pct=14, price=100, participation="Uygun Değil"),
                _row("SPUS", market_value=1500, weight_pct=15, price=100, asset_class="etf"),
                _row("HLAL", market_value=1500, weight_pct=15, price=100, asset_class="etf"),
            ]
        )
        plan = _plan(view=view, policy=_policy(equity=70, etf=30), candidates=[], amount="100000")
        self.assertTrue(plan.recommendations)
        self.assertTrue(all(row.layer == "etf" for row in plan.recommendations))
        self.assertGreater(plan.residual_cash, Decimal("0"))
        self.assertLess(plan.total_allocated, plan.input_amount)
        self.assertLessEqual(plan.total_allocated, Decimal("40000"))

    def test_g_empty_book_first_lira_bootstrap(self) -> None:
        plan = _plan(
            view=_view([]),
            policy=_policy(equity=70, etf=30),
            candidates=[
                _candidate("CRM", "GÜÇLÜ ADAY"),
                _candidate("SPUS", "ADAY", asset_type="ETF"),
            ],
            amount="100000",
        )
        self.assertTrue(plan.recommendations)
        self.assertGreater(plan.total_allocated, 0)
        symbols = {row.symbol for row in plan.recommendations}
        self.assertTrue(symbols & {"CRM", "SPUS"})
        self.assertEqual(plan.total_allocated + plan.residual_cash, plan.input_amount)

    def test_h_concentration_blocks_or_reduces(self) -> None:
        view = _view(
            [
                _row("AAPL", market_value=2800, weight_pct=28, price=100),
                _row("SPUS", market_value=7200, weight_pct=72, price=100, asset_class="etf"),
            ]
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[],
            amount="100000",
        )
        self.assertNotIn("AAPL", [row.symbol for row in plan.recommendations])
        self.assertTrue(
            any(
                row.symbol == "AAPL" and row.reason_code == REASON_CONCENTRATION_LIMIT
                for row in plan.skipped
            )
        )
        self.assertEqual(plan.residual_cash, Decimal("100000"))

    def test_i_fx_unavailable_leaves_residual(self) -> None:
        view = _view(
            [_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("CRM", "GÜÇLÜ ADAY")],
            amount="100000",
            conversion=None,
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertTrue(any(row.reason_code == REASON_FX_REQUIRED for row in plan.skipped))

    def test_j_no_eligible_securities_is_valid_residual(self) -> None:
        plan = _plan(
            view=_view([]),
            policy=_policy(equity=70, etf=30),
            candidates=[],
            amount="100000",
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.residual_cash, Decimal("100000"))
        self.assertIn("UNFILLED_UNDERWEIGHT:equity", plan.limitations)
        self.assertIn("RESIDUAL_CASH", plan.limitations)


class SafetyTests(unittest.TestCase):
    def test_no_writes_or_providers(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        lower = source.lower()
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token.lower(), lower)
        for token in WRITE_TOKENS:
            self.assertNotIn(token, source)
        self.assertNotIn("buy ", source.lower())
        self.assertIn("allocate_new_money", source)


if __name__ == "__main__":
    unittest.main()
