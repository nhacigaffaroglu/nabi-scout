from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.fund_intelligence_engine import (
    evaluate_fund_intelligence,
    evaluate_fund_participation_gate,
    fund_participation_status_for_decision,
    profile_for_mandate,
)
from services.fund_lookthrough_summary import build_fund_lookthrough_summary
from services.fund_product_contract import (
    DIM_COST_EVAL,
    DIM_COUNTRY_CONCENTRATION,
    DIM_CREDIT_QUALITY,
    DIM_CURRENCY_EXPOSURE,
    DIM_DURATION,
    DIM_ISSUER_CONCENTRATION,
    DIM_PARTICIPATION_MANDATE,
    DIM_PORTFOLIO_FIT_EVAL,
    DIM_REAL_ESTATE_CONCENTRATION,
    DIM_STATUS_MISSING,
    DIM_STATUS_NOT_APPLICABLE,
    DIM_STATUS_READY,
    DIM_YIELD,
    PILOT_FUND_SYMBOLS,
    PROFILE_EQUITY_ETF,
    PROFILE_REIT_ETF,
    PROFILE_SUKUK_ETF,
    PurificationFactor,
)
from services.hybrid_exposure_allocation_policy import HybridPortfolioMode
from services.official_fund_holdings_client import parse_official_holdings_csv
from services.official_sp_funds_product import OfficialSpFundsProductProvider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_AVOID,
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REVIEW,
    DECISION_WATCH,
    REASON_FUND_INTELLIGENCE_MISSING,
    PortfolioSecurityContext,
)
from services.portfolio_security_decision_engine import (
    evaluate_portfolio_security_decision,
    supports_fund_portfolio_decision,
    supports_portfolio_decision,
)
from services.security_intelligence_contract import (
    STATE_ATTRACTIVE,
    STATE_AVOID,
    STATE_CAUTION,
    STATE_INSUFFICIENT_DATA,
    STATE_WATCH,
)
from services.wealth_new_money_allocation import (
    REASON_EXISTING_HOLDING_TOPUP,
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED,
    allocate_new_money,
)
from tests.fixtures.sp_funds_official import PRODUCT_HTML, PURIFICATION_HTML
from tests.test_nabi_adviser_8f import _psd
from tests.test_official_fund_holdings import _csv, _row as _holding_row
from tests.test_portfolio_security_decision import _healthy as _equity_ctx
from tests.test_wealth_new_money_allocation import _exposure_policy, _fx, _row, _view


ENGINE = Path("services/fund_intelligence_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
EIGHT_E = Path("services/portfolio_security_decision_engine.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
)
WRITE_TOKENS = (".insert(", ".upsert(", ".delete(", "post_transaction")


def _provider() -> OfficialSpFundsProductProvider:
    return OfficialSpFundsProductProvider(
        product_html=PRODUCT_HTML,
        purification_html=PURIFICATION_HTML,
    )


def _lookthrough(symbol: str, rows: list[str] | None = None):
    parsed = parse_official_holdings_csv(
        _csv(
            symbol,
            rows
            or [
                _holding_row(symbol, "AAPL", "Apple", "20.00%"),
                _holding_row(symbol, "MSFT", "Microsoft", "15.00%"),
                _holding_row(symbol, "NVDA", "Nvidia", "10.00%"),
            ],
        ),
        fund_symbol=symbol,
    )
    return build_fund_lookthrough_summary(parsed)


def _eval(symbol: str, **overrides):
    provider = _provider()
    kwargs = dict(
        facts=provider.facts(symbol),
        mandate=provider.mandate(symbol),
        sharia=provider.sharia_evidence(symbol),
        purification=provider.purification_evidence(symbol),
        lookthrough=_lookthrough(symbol),
    )
    kwargs.update(overrides)
    return evaluate_fund_intelligence(**kwargs)


def _ana_view():
    return _view(
        [
            _row("AAPL", market_value=800, weight_pct=8, price=100),
            _row("CRM", market_value=800, weight_pct=8, price=100),
            _row("ASELS", market_value=500, weight_pct=5, price=100),
            _row("BIMAS", market_value=500, weight_pct=5, price=100),
            _row("TUPRS", market_value=400, weight_pct=4, price=100),
            _row("SPUS", market_value=2500, weight_pct=25, price=100, asset_class="etf"),
            _row("SPSK", market_value=1500, weight_pct=15, price=100, asset_class="etf"),
            _row("SPRE", market_value=1000, weight_pct=10, price=100, asset_class="etf"),
            _row("SPWO", market_value=1000, weight_pct=10, price=100, asset_class="etf"),
            _row("TSLA", market_value=1000, weight_pct=10, price=100),
        ]
    )


def _fund_ctx(symbol: str, **kwargs) -> PortfolioSecurityContext:
    defaults = dict(
        symbol=symbol,
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=False,
        si_state=STATE_INSUFFICIENT_DATA,
        is_holding=True,
        portfolio_weight=10.0,
        instrument_type="ETF",
        market="US",
        economic_exposure_status=HybridPortfolioMode.COMPLETE.value,
    )
    defaults.update(kwargs)
    return PortfolioSecurityContext(**defaults)


class DimensionAndThresholdTests(unittest.TestCase):
    def test_profiles_and_type_specific_dimensions(self) -> None:
        provider = _provider()
        self.assertEqual(profile_for_mandate(provider.mandate("SPUS")), PROFILE_EQUITY_ETF)
        self.assertEqual(profile_for_mandate(provider.mandate("SPSK")), PROFILE_SUKUK_ETF)
        self.assertEqual(profile_for_mandate(provider.mandate("SPRE")), PROFILE_REIT_ETF)
        self.assertEqual(profile_for_mandate(provider.mandate("SPWO")), PROFILE_EQUITY_ETF)
        spus = {row.name: row.status for row in _eval("SPUS").dimensions}
        spsk = {row.name: row.status for row in _eval("SPSK").dimensions}
        spre = {row.name: row.status for row in _eval("SPRE").dimensions}
        spwo = {row.name: row.status for row in _eval("SPWO").dimensions}
        self.assertEqual(spus[DIM_DURATION], DIM_STATUS_NOT_APPLICABLE)
        self.assertEqual(spus[DIM_REAL_ESTATE_CONCENTRATION], DIM_STATUS_NOT_APPLICABLE)
        self.assertEqual(spsk[DIM_DURATION], DIM_STATUS_MISSING)
        self.assertEqual(spsk[DIM_YIELD], DIM_STATUS_MISSING)
        self.assertEqual(spsk[DIM_CREDIT_QUALITY], DIM_STATUS_MISSING)
        self.assertEqual(spsk[DIM_ISSUER_CONCENTRATION], DIM_STATUS_MISSING)
        self.assertEqual(spsk[DIM_REAL_ESTATE_CONCENTRATION], DIM_STATUS_NOT_APPLICABLE)
        self.assertEqual(spre[DIM_REAL_ESTATE_CONCENTRATION], DIM_STATUS_MISSING)
        self.assertEqual(spre[DIM_DURATION], DIM_STATUS_NOT_APPLICABLE)
        self.assertEqual(spwo[DIM_COUNTRY_CONCENTRATION], DIM_STATUS_MISSING)
        self.assertEqual(spwo[DIM_CURRENCY_EXPOSURE], DIM_STATUS_MISSING)
        self.assertEqual(spus[DIM_PORTFOLIO_FIT_EVAL], DIM_STATUS_NOT_APPLICABLE)

    def test_minimum_evidence_threshold_and_missing_dims(self) -> None:
        evaluation = _eval("SPUS")
        self.assertEqual(evaluation.state, STATE_INSUFFICIENT_DATA)
        self.assertIsNone(evaluation.score)
        self.assertIn("PERFORMANCE", evaluation.missing_evidence)
        self.assertIn("RISK", evaluation.missing_evidence)
        self.assertLess(evaluation.confidence, 0.55)
        rich = _eval(
            "SPUS",
            historical_performance_present=True,
            official_risk_series_present=True,
        )
        self.assertNotEqual(rich.state, STATE_INSUFFICIENT_DATA)
        self.assertIsNotNone(rich.score)

    def test_lookthrough_concentration_and_unknown_holdings(self) -> None:
        from services.fund_product_contract import FundLookthroughSummary, LookthroughHolding

        unknown = FundLookthroughSummary(
            fund_symbol="SPUS",
            as_of="2026-08-28",
            holdings_count=2,
            top_holding=LookthroughHolding("AAPL", "Apple", 60.0, True, False),
            top_holding_weight_pct=60.0,
            top10_weight_pct=100.0,
            single_name_concentration_pct=60.0,
            cash_other_weight_pct=0.0,
            unknown_weight_pct=40.0,
            sector_allocation=(),
            country_allocation=(),
            known_nabi_overlap=("AAPL",),
            limitation="SECTOR_UNKNOWN",
        )
        self.assertGreater(unknown.unknown_weight_pct, 0)
        evaluation = _eval("SPUS", lookthrough=unknown)
        conc = next(row for row in evaluation.dimensions if row.name == "CONCENTRATION")
        self.assertEqual(conc.status, DIM_STATUS_MISSING)

    def test_official_sharia_gate_not_ticker(self) -> None:
        provider = _provider()
        gate = evaluate_fund_participation_gate(provider.sharia_evidence("SPUS"))
        self.assertTrue(gate.eligible)
        self.assertEqual(fund_participation_status_for_decision(gate), PARTICIPATION_STATUS_UYGUN)
        missing = evaluate_fund_participation_gate(None)
        self.assertFalse(missing.eligible)
        name_only = evaluate_fund_intelligence(
            facts=provider.facts("SPUS"),
            mandate=provider.mandate("SPUS"),
            sharia=None,
        )
        self.assertFalse(name_only.participation.eligible)
        self.assertEqual(name_only.state, STATE_INSUFFICIENT_DATA)

    def test_purification_does_not_change_score(self) -> None:
        provider = _provider()
        base = provider.purification_evidence("SPUS")
        mutated = type(base)(
            symbol=base.symbol,
            purification_required=base.purification_required,
            latest_factor_pct=99.0,
            factor_period=base.factor_period,
            source=base.source,
            source_url=base.source_url,
            as_of=base.as_of,
            methodology=base.methodology,
            factors=(
                PurificationFactor(
                    symbol="SPUS",
                    period="Q1 2026",
                    factor_pct=99.0,
                    source=base.source,
                    source_url=base.source_url,
                ),
            ),
            limitations=base.limitations,
        )
        first = _eval("SPUS", purification=base, historical_performance_present=True, official_risk_series_present=True)
        second = _eval("SPUS", purification=mutated, historical_performance_present=True, official_risk_series_present=True)
        self.assertEqual(first.score, second.score)
        self.assertEqual(first.state, second.state)
        self.assertNotEqual(first.purification_factor_pct, second.purification_factor_pct)


class EightEMappingTests(unittest.TestCase):
    def test_state_mapping_and_missing_intelligence(self) -> None:
        missing = evaluate_portfolio_security_decision(_fund_ctx("SPSK", si_state=None))
        self.assertEqual(missing.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(missing.exposure_increase_allowed)
        self.assertIn(REASON_FUND_INTELLIGENCE_MISSING, missing.blocking_reasons)
        insufficient = evaluate_portfolio_security_decision(_fund_ctx("SPSK"))
        self.assertEqual(insufficient.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(insufficient.exposure_increase_allowed)
        attractive = evaluate_portfolio_security_decision(
            _fund_ctx("SPSK", si_state=STATE_ATTRACTIVE)
        )
        self.assertEqual(attractive.decision, DECISION_CONSIDER_TOP_UP)
        self.assertTrue(attractive.exposure_increase_allowed)
        watch = evaluate_portfolio_security_decision(_fund_ctx("SPSK", si_state=STATE_WATCH))
        self.assertEqual(watch.decision, DECISION_WATCH)
        caution = evaluate_portfolio_security_decision(_fund_ctx("SPSK", si_state=STATE_CAUTION))
        self.assertEqual(caution.decision, DECISION_REVIEW)
        avoid_held = evaluate_portfolio_security_decision(_fund_ctx("SPSK", si_state=STATE_AVOID))
        self.assertEqual(avoid_held.decision, DECISION_HOLD)
        avoid_new = evaluate_portfolio_security_decision(
            _fund_ctx("SPWO", si_state=STATE_AVOID, is_holding=False, portfolio_weight=0.0)
        )
        self.assertEqual(avoid_new.decision, DECISION_AVOID)
        self.assertTrue(supports_portfolio_decision(instrument_type="ETF", symbol="SPSK"))
        self.assertTrue(supports_fund_portfolio_decision("ETF"))

    def test_equity_isolation(self) -> None:
        aapl = evaluate_portfolio_security_decision(
            _equity_ctx(
                symbol="AAPL",
                si_state=STATE_WATCH,
                is_holding=True,
                portfolio_weight=8.0,
                economic_exposure_status=HybridPortfolioMode.COMPLETE.value,
            )
        )
        self.assertNotEqual(aapl.decision, DECISION_INSUFFICIENT_DATA)
        self.assertNotIn(REASON_FUND_INTELLIGENCE_MISSING, aapl.blocking_reasons)


class NewMoneyFundGateTests(unittest.TestCase):
    def test_spsk_mandate_only_does_not_top_up(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
        )
        self.assertNotIn("SPSK", [row.symbol for row in plan.recommendations])
        self.assertFalse(
            any(
                row.symbol == "SPSK" and row.reason_code == REASON_EXISTING_HOLDING_TOPUP
                for row in plan.recommendations
            )
        )
        self.assertTrue(
            any(
                row.symbol == "SPSK" and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in plan.skipped
            )
        )
        self.assertNotAlmostEqual(
            sum(row.allocated_amount for row in plan.recommendations if row.symbol == "SPSK"),
            Decimal("6746.52"),
        )

    def test_insufficient_and_non_increase_block(self) -> None:
        blocked = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
            security_decisions=tuple(
                _psd(symbol, DECISION_INSUFFICIENT_DATA, increase=False)
                for symbol in PILOT_FUND_SYMBOLS
            ),
        )
        self.assertEqual(
            sum(row.allocated_amount for row in blocked.recommendations if row.symbol in PILOT_FUND_SYMBOLS),
            Decimal("0"),
        )
        watch = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
            security_decisions=(_psd("SPSK", DECISION_WATCH, increase=False),),
        )
        self.assertNotIn("SPSK", [row.symbol for row in watch.recommendations])

    def test_valid_increase_can_reach_candidate_stage(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
            security_decisions=(_psd("SPSK", DECISION_CONSIDER_TOP_UP, increase=True),),
        )
        self.assertFalse(
            any(
                row.symbol == "SPSK" and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in plan.skipped
            )
        )

    def test_hybrid_off_and_no_writes(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
        )
        self.assertFalse(plan.hybrid_allocation_active)
        self.assertNotIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)
        for path in (ENGINE, NEW_MONEY, EIGHT_E):
            source = path.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token, source)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
            self.assertNotIn('if symbol == "SPSK"', source)


class PilotEvaluationTests(unittest.TestCase):
    def test_official_pilot_is_insufficient_without_history(self) -> None:
        for symbol in PILOT_FUND_SYMBOLS:
            evaluation = _eval(symbol)
            self.assertEqual(evaluation.state, STATE_INSUFFICIENT_DATA)
            self.assertTrue(evaluation.participation.eligible)
            cost = next(row for row in evaluation.dimensions if row.name == DIM_COST_EVAL)
            self.assertEqual(cost.status, DIM_STATUS_READY)
            part = next(row for row in evaluation.dimensions if row.name == DIM_PARTICIPATION_MANDATE)
            self.assertEqual(part.status, DIM_STATUS_READY)
            eight_e = evaluate_portfolio_security_decision(
                _fund_ctx(
                    symbol,
                    si_state=evaluation.state,
                    participation_status=fund_participation_status_for_decision(evaluation.participation),
                )
            )
            self.assertEqual(eight_e.decision, DECISION_INSUFFICIENT_DATA)
            self.assertFalse(eight_e.exposure_increase_allowed)


if __name__ == "__main__":
    unittest.main()
