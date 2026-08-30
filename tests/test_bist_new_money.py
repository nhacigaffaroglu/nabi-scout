from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    AllocationPolicy,
    AllocationProvenance,
    AllocationTarget,
    _map_market,
)
from services.portfolio_security_decision_contract import (
    DECISION_AVOID,
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REVIEW,
    DECISION_WATCH,
)
from services.wealth_new_money_allocation import (
    REASON_CONCENTRATION_LIMIT,
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED,
    REASON_PARTICIPATION_BLOCKED,
    REASON_STRONG_CANDIDATE,
    allocate_new_money,
)
from tests.test_nabi_adviser_8f import _psd
from tests.test_wealth_new_money_allocation import _candidate, _plan, _policy, _row, _view


ENGINE = Path("services/wealth_new_money_allocation.py")
ALLOC = Path("services/portfolio_allocation_intelligence.py")
FIXTURE = "EQBISTX"


def _market_policy(*, tr: float, us: float, other: float = 0.0) -> AllocationPolicy:
    return AllocationPolicy(
        targets=(
            AllocationTarget("tr", AllocationDimension.MARKET, tr),
            AllocationTarget("us", AllocationDimension.MARKET, us),
            AllocationTarget("other", AllocationDimension.MARKET, other),
        ),
        provenance=AllocationProvenance.USER_DEFINED,
    )


def _bist_asset(symbol: str, market: str = "IST") -> dict:
    return {
        "id": f"as-{symbol}",
        "symbol": symbol,
        "market": market,
        "asset_class": "equity",
        "currency": "TRY",
    }


class MarketAliasTests(unittest.TestCase):
    def test_bist_family_maps_to_tr_without_symbol_logic(self) -> None:
        for raw in ("BIST", "XIST", "IST", "TR", "ISTANBUL", "TURKEY", "TURKIYE"):
            self.assertEqual(_map_market(raw), "tr", raw)
        self.assertEqual(_map_market("US"), "us")
        self.assertEqual(_map_market("USA"), "us")
        self.assertEqual(_map_market("ABD"), "us")
        self.assertEqual(_map_market("NASDAQ"), "other")
        self.assertEqual(_map_market("NYSE"), "other")
        source = ALLOC.read_text(encoding="utf-8")
        self.assertNotIn("ASELS", source)
        self.assertNotIn("if symbol", source.split("def _map_market")[1][:400])


class ExistingHoldingFirewallTests(unittest.TestCase):
    def test_watch_holdings_do_not_receive_new_money(self) -> None:
        view = _view(
            [
                _row("ASELS", market_value=5702, weight_pct=6.52, price=404, currency="TRY"),
                _row("BIMAS", market_value=13813, weight_pct=15.79, price=415.5, currency="TRY"),
                _row("TUPRS", market_value=8492, weight_pct=9.71, price=396, currency="TRY"),
                _row("SPUS", market_value=59000, weight_pct=67.98, price=100, asset_class="etf"),
            ]
        )
        decisions = (
            _psd("ASELS", DECISION_WATCH, increase=False, si_state="WATCH"),
            _psd("BIMAS", DECISION_WATCH, increase=False, si_state="WATCH"),
            _psd("TUPRS", DECISION_WATCH, increase=False, si_state="WATCH"),
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=decisions,
            assets=[_bist_asset(symbol) for symbol in ("ASELS", "BIMAS", "TUPRS")],
        )
        allocated = {row.symbol for row in plan.recommendations}
        self.assertFalse(allocated & {"ASELS", "BIMAS", "TUPRS"})
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            self.assertTrue(
                any(
                    row.symbol == symbol
                    and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                    for row in plan.skipped
                ),
                symbol,
            )
        self.assertGreater(plan.residual_cash, 0)

    def test_eight_e_firewall_states(self) -> None:
        view = _view(
            [
                _row("ASELS", market_value=1000, weight_pct=10, price=100, currency="TRY"),
                _row("SPUS", market_value=9000, weight_pct=90, price=100, asset_class="etf"),
            ]
        )
        for decision in (
            DECISION_WATCH,
            DECISION_REVIEW,
            DECISION_HOLD,
            DECISION_AVOID,
            DECISION_INSUFFICIENT_DATA,
        ):
            plan = _plan(
                view=view,
                policy=_policy(equity=40, etf=60),
                candidates=[],
                security_decisions=(_psd("ASELS", decision, increase=False),),
                assets=[_bist_asset("ASELS")],
            )
            self.assertNotIn("ASELS", [row.symbol for row in plan.recommendations], decision)
            self.assertTrue(
                any(
                    row.symbol == "ASELS"
                    and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                    for row in plan.skipped
                ),
                decision,
            )


class ParticipationFirewallTests(unittest.TestCase):
    def test_kontrol_et_uygun_degil_and_missing_block(self) -> None:
        view = _view(
            [
                _row("ASELS", market_value=1000, weight_pct=10, price=100, currency="TRY", participation="Kontrol Et"),
                _row("BIMAS", market_value=1000, weight_pct=10, price=100, currency="TRY", participation="Uygun Değil"),
                _row("TUPRS", market_value=1000, weight_pct=10, price=100, currency="TRY", participation=None),
                _row("SPUS", market_value=7000, weight_pct=70, price=100, asset_class="etf"),
            ]
        )
        decisions = (
            _psd("ASELS", DECISION_CONSIDER_TOP_UP, increase=True),
            _psd("BIMAS", DECISION_CONSIDER_TOP_UP, increase=True),
            _psd("TUPRS", DECISION_CONSIDER_TOP_UP, increase=True),
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=decisions,
            assets=[_bist_asset(symbol) for symbol in ("ASELS", "BIMAS", "TUPRS")],
        )
        allocated = {row.symbol for row in plan.recommendations}
        self.assertFalse(allocated & {"ASELS", "BIMAS", "TUPRS"})
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            self.assertTrue(
                any(
                    row.symbol == symbol and row.reason_code == REASON_PARTICIPATION_BLOCKED
                    for row in plan.skipped
                ),
                symbol,
            )


class PositiveBistControlTests(unittest.TestCase):
    def test_existing_holding_top_up_when_8e_allows(self) -> None:
        view = _view(
            [
                _row(FIXTURE, market_value=1000, weight_pct=10, price=100),
                _row("SPUS", market_value=9000, weight_pct=90, price=100, asset_class="etf"),
            ]
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=(
                _psd(FIXTURE, DECISION_CONSIDER_TOP_UP, increase=True, si_state="ATTRACTIVE"),
            ),
            assets=[_bist_asset(FIXTURE, "XIST")],
        )
        rec = next(row for row in plan.recommendations if row.symbol == FIXTURE)
        self.assertEqual(rec.existing_or_new, "existing")
        self.assertEqual(rec.reason_code, REASON_EXISTING_HOLDING_TOPUP)
        self.assertGreater(rec.allocated_amount, 0)
        self.assertEqual(rec.allocated_amount % Decimal("100"), Decimal("0"))

    def test_nonholding_opportunity_when_8e_allows(self) -> None:
        view = _view(
            [_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")]
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[
                _candidate(
                    FIXTURE,
                    "GÜÇLÜ ADAY",
                    price=100,
                    market="IST",
                    currency="TRY",
                    asset_type="Hisse",
                )
            ],
            security_decisions=(
                _psd(FIXTURE, DECISION_CONSIDER_NEW_POSITION, increase=True, si_state="ATTRACTIVE"),
            ),
        )
        rec = next(row for row in plan.recommendations if row.symbol == FIXTURE)
        self.assertEqual(rec.existing_or_new, "new")
        self.assertEqual(rec.reason_code, REASON_STRONG_CANDIDATE)
        self.assertGreater(rec.allocated_amount, 0)

    def test_ist_alias_routes_to_tr_layer(self) -> None:
        view = _view(
            [
                _row("AAPL", market_value=8000, weight_pct=80, price=100),
                _row(FIXTURE, market_value=2000, weight_pct=20, price=100),
            ]
        )
        plan = _plan(
            view=view,
            policy=_market_policy(tr=40, us=60),
            candidates=[],
            assets=[
                {"id": "as-AAPL", "symbol": "AAPL", "market": "US", "asset_class": "equity"},
                _bist_asset(FIXTURE, "IST"),
            ],
            security_decisions=(
                _psd("AAPL", DECISION_WATCH, increase=False),
                _psd(FIXTURE, DECISION_CONSIDER_TOP_UP, increase=True),
            ),
        )
        self.assertIn(FIXTURE, [row.symbol for row in plan.recommendations])
        rec = next(row for row in plan.recommendations if row.symbol == FIXTURE)
        self.assertEqual(rec.layer, "tr")


class ConcentrationWholeShareResidualTests(unittest.TestCase):
    def _cap_plan(self, *, market_value: float, weight_pct: float):
        view = _view(
            [
                _row(FIXTURE, market_value=market_value, weight_pct=weight_pct, price=100),
                _row(
                    "SPUS",
                    market_value=10000 - market_value,
                    weight_pct=100 - weight_pct,
                    price=100,
                    asset_class="etf",
                ),
            ]
        )
        return _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=(_psd(FIXTURE, DECISION_CONSIDER_TOP_UP, increase=True),),
            assets=[_bist_asset(FIXTURE)],
        )

    def test_concentration_below_near_at_and_cross(self) -> None:
        below = self._cap_plan(market_value=1000, weight_pct=10)
        self.assertIn(FIXTURE, [row.symbol for row in below.recommendations])
        near = self._cap_plan(market_value=1900, weight_pct=19)
        allocated = {row.symbol for row in near.recommendations}
        if FIXTURE in allocated:
            rec = next(row for row in near.recommendations if row.symbol == FIXTURE)
            self.assertGreater(rec.allocated_amount, 0)
        at_current_cap = self._cap_plan(market_value=2000, weight_pct=20)
        if FIXTURE in {row.symbol for row in at_current_cap.recommendations}:
            rec = next(row for row in at_current_cap.recommendations if row.symbol == FIXTURE)
            self.assertGreater(rec.allocated_amount, 0)
        # Existing cap is 20% of the post-contribution book, not current weight.
        # 25% of a 10_000 book already exceeds that headroom after a 60_000 TRY add.
        cross = self._cap_plan(market_value=2500, weight_pct=25)
        self.assertTrue(
            any(
                row.symbol == FIXTURE and row.reason_code == REASON_CONCENTRATION_LIMIT
                for row in cross.skipped
            )
            or FIXTURE not in [row.symbol for row in cross.recommendations]
        )

    def test_residual_cash_when_no_eligible_candidate(self) -> None:
        view = _view([_row("SPUS", market_value=10000, weight_pct=100, price=100, asset_class="etf")])
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=(),
        )
        self.assertEqual(plan.recommendations, ())
        self.assertEqual(plan.residual_cash, Decimal("60000"))
        self.assertNotIn("CASH", [row.symbol for row in plan.recommendations])

    def test_engine_does_not_write(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("post_transaction", source)
        self.assertIn("Never writes", source)


class UsRegressionTests(unittest.TestCase):
    def test_aapl_crm_still_allocate_when_8e_allows(self) -> None:
        view = _view(
            [
                _row("AAPL", market_value=1000, weight_pct=10, price=100),
                _row("CRM", market_value=1000, weight_pct=10, price=100),
                _row("SPUS", market_value=8000, weight_pct=80, price=100, asset_class="etf"),
            ]
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=(
                _psd("AAPL", DECISION_CONSIDER_TOP_UP, increase=True),
                _psd("CRM", DECISION_CONSIDER_TOP_UP, increase=True),
            ),
        )
        symbols = {row.symbol for row in plan.recommendations}
        self.assertTrue({"AAPL", "CRM"} & symbols)


if __name__ == "__main__":
    unittest.main()
