from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.wealth_new_money_allocation_ui import (
    DEFAULT_MIN_TRADE,
    RESULT_STATE_KEY,
    render_new_money_allocation,
)
from services.wealth_goal_models import ContributionPlan, default_contribution_plan
from services.wealth_new_money_allocation import (
    AllocationPlan,
    REASON_BELOW_MIN_TRADE,
    REASON_INSUFFICIENT_CASH,
    REASON_NOT_ACTIONABLE,
    allocate_new_money,
)
from services.wealth_new_money_allocation_presentation import (
    EXISTING_LABEL,
    EXTRA_CAPTION,
    MIN_TRADE_LABEL,
    MODE_EXTRA,
    MODE_MONTHLY,
    NEW_LABEL,
    RESIDUAL_LABEL,
    RESIDUAL_NOTE,
    RUN_LABEL,
    SECTION_TITLE,
    SKIPPED_EXPANDER,
    TOTAL_ALLOCATED_LABEL,
    format_quantity,
)
from tests.test_wealth_new_money_allocation import (
    _candidate,
    _fx,
    _policy,
    _row,
    _view,
)

UI = Path("components/wealth_new_money_allocation_ui.py")
PRES = Path("services/wealth_new_money_allocation_presentation.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "alpha_vantage",
    "TwelveData",
    "twelve_data",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "BorsaIstanbul",
    "borsaistanbul",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    ".update(",
    "capture_portfolio_snapshot",
    "save_policy",
    "save_planning_fx_schedule",
)
EXECUTION_TOKENS = (
    "Buy",
    "Satın al",
    "Confirm purchase",
    "Execute",
    "Post transaction",
    "Emir gönder",
)


class _Box:
    def __init__(self, parent: "DummySt"):
        self.parent = parent

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def metric(self, label, value, **kwargs):
        self.parent.metrics.append((str(label), str(value)))
        self.parent.texts.append(f"{label}: {value}")

    def markdown(self, text, **kwargs):
        self.parent.markdowns.append(str(text))

    def write(self, text, **kwargs):
        self.parent.writes.append(str(text))

    def caption(self, text, **kwargs):
        self.parent.captions.append(str(text))


class DummySt:
    def __init__(
        self,
        *,
        mode: str = MODE_MONTHLY,
        extra_amount: float = 40000.0,
        min_trade: float = 0.0,
        clicked: bool = False,
        session_state: dict | None = None,
    ):
        self.mode = mode
        self.extra_amount = extra_amount
        self.min_trade = min_trade
        self.clicked = clicked
        self.session_state = session_state if session_state is not None else {}
        self.markdowns: list[str] = []
        self.writes: list[str] = []
        self.captions: list[str] = []
        self.infos: list[str] = []
        self.metrics: list[tuple[str, str]] = []
        self.buttons: list[str] = []
        self.number_inputs: list[str] = []
        self.texts: list[str] = []

    def markdown(self, text, **kwargs):
        self.markdowns.append(str(text))

    def write(self, text, **kwargs):
        self.writes.append(str(text))

    def caption(self, text, **kwargs):
        self.captions.append(str(text))

    def info(self, text, **kwargs):
        self.infos.append(str(text))

    def warning(self, text, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def metric(self, label, value, **kwargs):
        self.metrics.append((str(label), str(value)))
        self.texts.append(f"{label}: {value}")

    def radio(self, label, options, **kwargs):
        return self.mode

    def number_input(self, label, **kwargs):
        self.number_inputs.append(str(label))
        if MIN_TRADE_LABEL in str(label):
            return float(self.min_trade)
        return float(self.extra_amount)

    def button(self, label, **kwargs):
        self.buttons.append(str(label))
        return self.clicked and str(label) == RUN_LABEL

    def columns(self, count):
        size = count if isinstance(count, int) else len(count)
        return [_Box(self) for _ in range(size)]

    def container(self, *args, **kwargs):
        return _Box(self)

    def expander(self, label, **kwargs):
        self.captions.append(str(label))
        return _Box(self)

    def rerun(self):
        return None


def _blob(dummy: DummySt) -> str:
    return "\n".join(
        dummy.markdowns
        + dummy.writes
        + dummy.captions
        + dummy.infos
        + dummy.texts
        + [f"{label}: {value}" for label, value in dummy.metrics]
    )


def _patch(dummy: DummySt):
    return (
        patch("components.wealth_new_money_allocation_ui.st", dummy),
        patch("components.nabi_design_system._st", return_value=dummy),
    )


def _wealth() -> MagicMock:
    wealth = MagicMock()
    wealth.client = None
    wealth.user_id = "user-1"
    wealth.list_assets.return_value = []
    wealth.list_positions.return_value = []
    wealth.post_transaction = MagicMock()
    return wealth


def _empty_result() -> AllocationPlan:
    return AllocationPlan(
        input_amount=Decimal("0"),
        currency="TRY",
        recommendations=(),
        total_allocated=Decimal("0"),
        residual_cash=Decimal("0"),
        skipped=(),
    )


def _canonical_plan() -> ContributionPlan:
    return default_contribution_plan()


def _custom_monthly(amount: str) -> ContributionPlan:
    return ContributionPlan(
        starting_monthly=Decimal(amount),
        currency="TRY",
        annual_increase_rate=Decimal("0.25"),
    )


def _underweight_view():
    return _view(
        [_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]
    )


class ModeAndInputTests(unittest.TestCase):
    def test_monthly_mode_uses_canonical_contribution_amount(self) -> None:
        dummy = DummySt(mode=MODE_MONTHLY, clicked=True)
        allocate = MagicMock(return_value=_empty_result())
        plan = _canonical_plan()
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=plan,
                policy=_policy(equity=80, etf=20),
                candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
                conversion=_fx(),
                allocate_fn=allocate,
                session_state=dummy.session_state,
            )
        allocate.assert_called_once()
        kwargs = allocate.call_args.kwargs
        self.assertEqual(kwargs["available_amount"], plan.starting_monthly)
        self.assertEqual(kwargs["available_amount"], Decimal("60000"))
        self.assertEqual(kwargs["amount_currency"], plan.currency)
        self.assertEqual(kwargs["minimum_trade_amount"], DEFAULT_MIN_TRADE)
        self.assertIn(SECTION_TITLE, _blob(dummy))
        self.assertTrue(any("60,000 TL" in value or "60000" in value for _, value in dummy.metrics))

    def test_monthly_mode_does_not_hardcode_amount_when_plan_differs(self) -> None:
        dummy = DummySt(mode=MODE_MONTHLY, clicked=True)
        allocate = MagicMock(return_value=_empty_result())
        plan = _custom_monthly("75000")
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=plan,
                policy=_policy(equity=80, etf=20),
                candidates=[],
                conversion=_fx(),
                allocate_fn=allocate,
                session_state=dummy.session_state,
            )
        self.assertEqual(allocate.call_args.kwargs["available_amount"], Decimal("75000"))

    def test_extra_money_mode_accepts_temporary_amount(self) -> None:
        dummy = DummySt(mode=MODE_EXTRA, extra_amount=40000.0, clicked=True)
        allocate = MagicMock(return_value=_empty_result())
        wealth = _wealth()
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=wealth,
                plan=_canonical_plan(),
                policy=_policy(equity=80, etf=20),
                candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
                conversion=_fx(),
                allocate_fn=allocate,
                session_state=dummy.session_state,
            )
        self.assertEqual(allocate.call_args.kwargs["available_amount"], Decimal("40000.0"))
        self.assertIn(EXTRA_CAPTION, dummy.captions)
        wealth.post_transaction.assert_not_called()
        self.assertFalse(hasattr(wealth, "save_contribution_plan") and wealth.save_contribution_plan.called)

    def test_button_required_to_call_allocation_service(self) -> None:
        dummy = DummySt(mode=MODE_MONTHLY, clicked=False)
        allocate = MagicMock()
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=_canonical_plan(),
                policy=_policy(equity=80, etf=20),
                candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
                conversion=_fx(),
                allocate_fn=allocate,
                session_state=dummy.session_state,
            )
        allocate.assert_not_called()
        self.assertIn(RUN_LABEL, dummy.buttons)
        self.assertNotIn(RESULT_STATE_KEY, dummy.session_state)


class RecommendationRenderTests(unittest.TestCase):
    def test_recommendations_existing_new_quantity_residual_skipped(self) -> None:
        view = _view(
            [
                _row("AAPL", market_value=4000, weight_pct=40, price=100),
                _row("SPUS", market_value=6000, weight_pct=60, price=100, asset_class="etf"),
            ]
        )
        result = allocate_new_money(
            available_amount=Decimal("6000"),
            amount_currency="TRY",
            portfolio_view=view,
            policy=_policy(equity=80, etf=20),
            candidates=[_candidate("MSFT", "GÜÇLÜ ADAY", price=100)],
            conversion=_fx(),
        )
        dummy = DummySt(clicked=False, session_state={RESULT_STATE_KEY: result})
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=view,
                wealth=_wealth(),
                plan=_canonical_plan(),
                policy=_policy(equity=80, etf=20),
                candidates=[_candidate("MSFT", "GÜÇLÜ ADAY", price=100)],
                conversion=_fx(),
                session_state=dummy.session_state,
            )
        text = _blob(dummy)
        self.assertIn("AAPL", text)
        self.assertIn(EXISTING_LABEL, text)
        if any(row.existing_or_new == "new" for row in result.recommendations):
            self.assertIn(NEW_LABEL, text)
        aapl = next(row for row in result.recommendations if row.symbol == "AAPL")
        self.assertIn(format_quantity(aapl.quantity), text)
        self.assertEqual(aapl.quantity, aapl.quantity.to_integral_value())
        self.assertIn(TOTAL_ALLOCATED_LABEL, text)
        self.assertIn(RESIDUAL_LABEL, text)
        if result.residual_cash > 0:
            self.assertIn(RESIDUAL_NOTE, text)
        if result.skipped:
            self.assertIn(SKIPPED_EXPANDER, text)

    def test_skipped_reasons_displayed_from_engine(self) -> None:
        result = allocate_new_money(
            available_amount=Decimal("2000"),
            amount_currency="TRY",
            portfolio_view=_underweight_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "ADAY", price=100)],
            conversion=_fx(),
        )
        self.assertTrue(any(row.reason_code == REASON_INSUFFICIENT_CASH for row in result.skipped))
        dummy = DummySt(clicked=False, session_state={RESULT_STATE_KEY: result})
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=_canonical_plan(),
                policy=_policy(equity=70, etf=30),
                candidates=[_candidate("MSFT", "ADAY", price=100)],
                conversion=_fx(),
                session_state=dummy.session_state,
            )
        text = _blob(dummy)
        self.assertIn(SKIPPED_EXPANDER, text)
        self.assertIn("MSFT", text)
        self.assertIn("Tek lot için nakit yetersiz.", text)
        self.assertIn(RESIDUAL_LABEL, text)
        self.assertIn(RESIDUAL_NOTE, text)

    def test_below_min_trade_skip_is_translated(self) -> None:
        result = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_underweight_view(),
            policy=_policy(equity=70, etf=30),
            candidates=[_candidate("MSFT", "ADAY", price=100)],
            conversion=_fx(),
            minimum_trade_amount=Decimal("100000"),
        )
        self.assertTrue(any(row.reason_code == REASON_BELOW_MIN_TRADE for row in result.skipped))
        dummy = DummySt(clicked=False, session_state={RESULT_STATE_KEY: result})
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=_canonical_plan(),
                session_state=dummy.session_state,
            )
        self.assertIn("Minimum işlem tutarının altında.", _blob(dummy))


class EligibilityAndSafetyTests(unittest.TestCase):
    def test_valuation_only_bist_row_not_surfaced_as_new_opportunity(self) -> None:
        candidates = [
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
        dummy = DummySt(mode=MODE_MONTHLY, clicked=True)
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=_canonical_plan(),
                policy=_policy(equity=40, etf=60),
                candidates=candidates,
                conversion=_fx(),
                session_state=dummy.session_state,
            )
        result = dummy.session_state[RESULT_STATE_KEY]
        self.assertNotIn("TUPRS", [row.symbol for row in result.recommendations])
        self.assertTrue(
            any(row.symbol == "TUPRS" and row.reason_code == REASON_NOT_ACTIONABLE for row in result.skipped)
        )
        text = _blob(dummy)
        self.assertIn("TUPRS", text)
        self.assertIn("İşlem yapılabilir karar yok.", text)
        for line in dummy.markdowns:
            if "TUPRS" in line:
                self.assertNotIn(NEW_LABEL, line)

    def test_ui_does_not_select_all_candidates(self) -> None:
        dummy = DummySt(clicked=True)
        with _patch(dummy)[0], _patch(dummy)[1]:
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=_wealth(),
                plan=_canonical_plan(),
                policy=_policy(equity=80, etf=20),
                candidates=[
                    _candidate("MSFT", "GÜÇLÜ ADAY"),
                    _candidate("WATCH", "İZLE", asset_type="ETF"),
                ],
                conversion=_fx(),
                session_state=dummy.session_state,
            )
        result = dummy.session_state[RESULT_STATE_KEY]
        self.assertNotIn("WATCH", [row.symbol for row in result.recommendations])
        for line in dummy.markdowns:
            if "WATCH" in line:
                self.assertNotIn(NEW_LABEL, line)

    def test_no_execution_no_writes_no_providers(self) -> None:
        dummy = DummySt(clicked=True)
        wealth = _wealth()
        with _patch(dummy)[0], _patch(dummy)[1], patch(
            "services.current_market_data.fetch_fx_rate",
            side_effect=AssertionError("provider"),
        ), patch(
            "services.current_market_data.fetch_equity_quote",
            side_effect=AssertionError("provider"),
        ):
            render_new_money_allocation(
                portfolio_view=_underweight_view(),
                wealth=wealth,
                plan=_canonical_plan(),
                policy=_policy(equity=80, etf=20),
                candidates=[_candidate("MSFT", "GÜÇLÜ ADAY")],
                conversion=_fx(),
                session_state=dummy.session_state,
            )
        wealth.post_transaction.assert_not_called()
        wealth.list_assets.assert_called()
        text = _blob(dummy).lower()
        self.assertNotIn("buy", text)
        self.assertNotIn("satın al", text)
        self.assertNotIn("execute", text)
        for path in (UI, PRES):
            source = path.read_text(encoding="utf-8")
            lower = source.lower()
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token.lower(), lower)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
            for token in EXECUTION_TOKENS:
                self.assertNotIn(token, source)
        self.assertIn("allocate_new_money", UI.read_text(encoding="utf-8"))
        self.assertNotIn("60000", UI.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
