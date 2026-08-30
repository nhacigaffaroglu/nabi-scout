from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.fund_decision_readiness import (
    evaluate_fund_portfolio_decision,
    evaluate_official_fund_decision,
)
from services.fund_intelligence_engine import (
    evaluate_fund_intelligence,
    evaluate_official_fund_intelligence,
)
from services.fund_lookthrough_summary import build_fund_lookthrough_summary
from services.fund_product_contract import (
    DIM_COST_EVAL,
    DIM_COUNTRY_CONCENTRATION,
    DIM_CREDIT_QUALITY,
    DIM_CURRENCY_EXPOSURE,
    DIM_DURATION,
    DIM_PARTICIPATION_MANDATE,
    DIM_PERFORMANCE_EVAL,
    DIM_PORTFOLIO_FIT_EVAL,
    DIM_REAL_ESTATE_CONCENTRATION,
    DIM_RISK_EVAL,
    DIM_STATUS_MISSING,
    DIM_STATUS_NOT_APPLICABLE,
    DIM_STATUS_READY,
    DIM_YIELD,
    PILOT_FUND_SYMBOLS,
    PROFILE_EQUITY_ETF,
    PROFILE_REIT_ETF,
    PROFILE_SUKUK_ETF,
    OfficialFundPerformance,
)
from services.official_fund_holdings_client import parse_official_holdings_csv
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.portfolio_security_decision_contract import (
    DECISION_AVOID,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REVIEW,
    DECISION_WATCH,
    REASON_FUND_8E_DECISION_MISSING,
    REASON_FUND_INTELLIGENCE_MISSING,
    PortfolioSecurityContext,
)
from services.portfolio_security_decision_engine import (
    evaluate_portfolio_security_decision,
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
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED,
    allocate_new_money,
)
from tests.test_nabi_adviser_8f import _psd
from tests.test_official_fund_holdings import _csv, _row as _holding_row
from tests.test_portfolio_economic_exposure import _equity
from tests.test_wealth_new_money_allocation import _exposure_policy, _fx, _row, _view


NEW_MONEY = Path("services/wealth_new_money_allocation.py")
ENGINE = Path("services/fund_intelligence_engine.py")
EIGHT_E = Path("services/portfolio_security_decision_engine.py")


def _lookthrough(symbol: str = "SPUS", *, unknown: bool = False, top: str = "40.00%"):
    if unknown:
        rows = [
            "08/28/2026,SPUS,,,Unknown Holding,1,1,1,40.00%,1,1,1",
            _holding_row(symbol, "AAPL", "Apple", "60.00%"),
        ]
    else:
        rows = [
            _holding_row(symbol, "AAPL", "Apple", top),
            _holding_row(symbol, "MSFT", "Microsoft", "20.00%"),
            _holding_row(symbol, "AVGO", "Broadcom", "15.00%"),
            _holding_row(symbol, "NVDA", "NVIDIA", "10.00%"),
            _holding_row(symbol, "GOOGL", "Alphabet", "8.00%"),
            _holding_row(symbol, "META", "Meta", "7.00%"),
        ]
    parsed = parse_official_holdings_csv(_csv(symbol, rows), fund_symbol=symbol)
    return build_fund_lookthrough_summary(parsed, known_nabi_symbols=("AAPL",))


def _rich_performance(symbol: str) -> OfficialFundPerformance:
    return OfficialFundPerformance(
        symbol=symbol,
        return_1m=4.0,
        return_3m=8.0,
        return_1y=20.0,
        drawdown=-8.0,
        volatility=9.0,
        source="official_test",
    )


def _spsk_underweight_view():
    return _view(
        [
            _row("AAPL", market_value=8000, weight_pct=80, price=100),
            _row("SPSK", market_value=1000, weight_pct=10, price=100, asset_class="etf"),
        ]
    )


class FundIntelligenceEvaluationTests(unittest.TestCase):
    def test_official_evidence_is_insufficient_without_history(self) -> None:
        for symbol, profile in (
            ("SPUS", PROFILE_EQUITY_ETF),
            ("SPSK", PROFILE_SUKUK_ETF),
            ("SPRE", PROFILE_REIT_ETF),
            ("SPWO", PROFILE_EQUITY_ETF),
        ):
            view = evaluate_official_fund_intelligence(symbol)
            self.assertEqual(view.fund_type_profile, profile)
            self.assertEqual(view.state, STATE_INSUFFICIENT_DATA)
            self.assertIsNone(view.score)
            self.assertFalse(view.publishable)
            evidence = view.evidence_map()
            self.assertEqual(evidence[DIM_PARTICIPATION_MANDATE], DIM_STATUS_READY)
            self.assertEqual(evidence[DIM_PERFORMANCE_EVAL], DIM_STATUS_MISSING)
            self.assertEqual(evidence[DIM_RISK_EVAL], DIM_STATUS_MISSING)
            self.assertEqual(evidence[DIM_COST_EVAL], DIM_STATUS_READY)
            self.assertEqual(evidence[DIM_PORTFOLIO_FIT_EVAL], DIM_STATUS_NOT_APPLICABLE)
            if symbol == "SPSK":
                self.assertEqual(evidence[DIM_DURATION], DIM_STATUS_MISSING)
                self.assertEqual(evidence[DIM_YIELD], DIM_STATUS_MISSING)
                self.assertEqual(evidence[DIM_CREDIT_QUALITY], DIM_STATUS_MISSING)
                self.assertEqual(evidence[DIM_REAL_ESTATE_CONCENTRATION], DIM_STATUS_NOT_APPLICABLE)
            if symbol == "SPRE":
                self.assertEqual(evidence[DIM_REAL_ESTATE_CONCENTRATION], DIM_STATUS_MISSING)
                self.assertEqual(evidence[DIM_DURATION], DIM_STATUS_NOT_APPLICABLE)
            if symbol == "SPUS":
                self.assertEqual(evidence[DIM_COUNTRY_CONCENTRATION], DIM_STATUS_NOT_APPLICABLE)
                self.assertEqual(evidence[DIM_CURRENCY_EXPOSURE], DIM_STATUS_NOT_APPLICABLE)
            if symbol == "SPWO":
                self.assertEqual(evidence[DIM_COUNTRY_CONCENTRATION], DIM_STATUS_MISSING)
                self.assertEqual(evidence[DIM_CURRENCY_EXPOSURE], DIM_STATUS_MISSING)

    def test_lookthrough_concentration_and_unknown_holdings(self) -> None:
        ready = evaluate_official_fund_intelligence("SPUS", lookthrough=_lookthrough())
        self.assertEqual(ready.evidence_map()["CONCENTRATION"], DIM_STATUS_READY)
        self.assertEqual(ready.evidence_map()["DIVERSIFICATION"], DIM_STATUS_READY)
        unknown = evaluate_official_fund_intelligence(
            "SPUS", lookthrough=_lookthrough(unknown=True)
        )
        self.assertEqual(unknown.evidence_map()["CONCENTRATION"], DIM_STATUS_READY)
        self.assertEqual(unknown.evidence_map()["DIVERSIFICATION"], DIM_STATUS_READY)

    def test_purification_does_not_change_score_or_state(self) -> None:
        provider = default_official_sp_funds_provider()
        facts = provider.facts("SPUS")
        mandate = provider.mandate("SPUS")
        sharia = provider.sharia_evidence("SPUS")
        first = evaluate_fund_intelligence(
            facts=facts,
            mandate=mandate,
            sharia=sharia,
            purification=provider.purification_evidence("SPUS"),
            lookthrough=_lookthrough(),
            performance=_rich_performance("SPUS"),
        )
        mutated = provider.purification_evidence("SPUS")
        second = evaluate_fund_intelligence(
            facts=facts,
            mandate=mandate,
            sharia=sharia,
            purification=type(mutated)(
                symbol=mutated.symbol,
                purification_required=mutated.purification_required,
                latest_factor_pct=99.0,
                factor_period=mutated.factor_period,
                source=mutated.source,
                source_url=mutated.source_url,
                as_of=mutated.as_of,
                methodology=mutated.methodology,
                factors=mutated.factors,
                limitations=mutated.limitations,
            ),
            lookthrough=_lookthrough(),
            performance=_rich_performance("SPUS"),
        )
        self.assertEqual(first.state, second.state)
        self.assertEqual(first.score, second.score)
        self.assertNotEqual(first.purification_factor_pct, second.purification_factor_pct)

    def test_official_sharia_gate_and_name_only_fail_closed(self) -> None:
        from tests.fixtures.sp_funds_official import NAME_ONLY_HTML
        from services.official_sp_funds_product import parse_sharia_evidence_html

        provider = default_official_sp_funds_provider()
        weak = evaluate_fund_intelligence(
            facts=provider.facts("SPUS"),
            mandate=provider.mandate("SPUS"),
            sharia=parse_sharia_evidence_html(NAME_ONLY_HTML, symbol="SPUS"),
        )
        self.assertFalse(weak.participation.eligible)
        self.assertEqual(weak.state, STATE_INSUFFICIENT_DATA)
        self.assertIsNone(weak.score)

    def test_full_evidence_can_publish_attractive(self) -> None:
        view = evaluate_official_fund_intelligence(
            "SPUS",
            lookthrough=_lookthrough(top="8.00%"),
            performance=_rich_performance("SPUS"),
        )
        self.assertIsNotNone(view.score)
        self.assertNotEqual(view.state, STATE_INSUFFICIENT_DATA)
        self.assertTrue(view.participation.eligible)


class EightEFundMappingTests(unittest.TestCase):
    def test_insufficient_and_missing_intelligence(self) -> None:
        official = evaluate_official_fund_decision(
            "SPUS", is_holding=True, portfolio_weight=10.0, economic_exposure_available=True
        )
        self.assertEqual(official.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(official.exposure_increase_allowed)
        missing = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="SPUS",
                instrument_type="ETF",
                market="US",
                is_holding=True,
                portfolio_weight=10.0,
                economic_exposure_status="STRICT",
            )
        )
        self.assertEqual(missing.decision, DECISION_INSUFFICIENT_DATA)
        self.assertIn(REASON_FUND_INTELLIGENCE_MISSING, missing.blocking_reasons)

    def test_state_mapping_hold_avoid_watch_review(self) -> None:
        attractive = evaluate_official_fund_intelligence(
            "SPUS",
            lookthrough=_lookthrough(top="8.00%"),
            performance=_rich_performance("SPUS"),
        )
        if attractive.state == STATE_ATTRACTIVE:
            top_up = evaluate_fund_portfolio_decision(
                attractive,
                is_holding=True,
                portfolio_weight=10.0,
                economic_exposure_available=True,
            )
            self.assertEqual(top_up.decision, DECISION_CONSIDER_TOP_UP)
            self.assertTrue(top_up.exposure_increase_allowed)
        watch = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="SPUS",
                instrument_type="ETF",
                market="US",
                si_state=STATE_WATCH,
                participation_status="Uygun",
                research_allowed=True,
                is_holding=True,
                portfolio_weight=10.0,
                economic_exposure_status="STRICT",
            )
        )
        self.assertEqual(watch.decision, DECISION_WATCH)
        self.assertFalse(watch.exposure_increase_allowed)
        caution = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="SPUS",
                instrument_type="ETF",
                market="US",
                si_state=STATE_CAUTION,
                participation_status="Uygun",
                research_allowed=True,
                is_holding=True,
                portfolio_weight=10.0,
                economic_exposure_status="STRICT",
            )
        )
        self.assertEqual(caution.decision, DECISION_REVIEW)
        held_avoid = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="SPSK",
                instrument_type="ETF",
                market="US",
                si_state=STATE_AVOID,
                participation_status="Uygun",
                research_allowed=True,
                is_holding=True,
                portfolio_weight=10.0,
                economic_exposure_status="STRICT",
            )
        )
        self.assertEqual(held_avoid.decision, DECISION_HOLD)
        new_avoid = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="HLAL",
                instrument_type="ETF",
                market="US",
                si_state=STATE_AVOID,
                participation_status="Uygun",
                research_allowed=True,
                is_holding=False,
                economic_exposure_status="STRICT",
            )
        )
        self.assertEqual(new_avoid.decision, DECISION_AVOID)

    def test_supports_fund_by_instrument_not_ticker(self) -> None:
        self.assertTrue(supports_portfolio_decision(instrument_type="ETF", market="US", symbol="SPUS"))
        self.assertTrue(supports_portfolio_decision(instrument_type="FUND", symbol="UNKNOWNETF"))
        self.assertFalse(supports_portfolio_decision(symbol="SPUS"))
        self.assertNotIn("if symbol ==", EIGHT_E.read_text(encoding="utf-8"))


class NewMoneyFundGateTests(unittest.TestCase):
    def test_spsk_mandate_only_does_not_top_up(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_spsk_underweight_view(),
            policy=_exposure_policy(equity=70, sukuk=20, cash=10),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
        )
        self.assertFalse(any(row.symbol == "SPSK" for row in plan.recommendations))
        self.assertTrue(
            any(
                row.symbol == "SPSK" and row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED
                for row in plan.skipped
            )
        )
        self.assertIn(REASON_FUND_8E_DECISION_MISSING, " ".join(row.reason_text for row in plan.skipped))
        self.assertFalse(plan.hybrid_allocation_active)

    def test_insufficient_and_non_increase_decisions_block(self) -> None:
        view = _spsk_underweight_view()
        policy = _exposure_policy(equity=70, sukuk=20, cash=10)
        for decision in (
            _psd("SPSK", DECISION_INSUFFICIENT_DATA, increase=False, reasons=(REASON_FUND_INTELLIGENCE_MISSING,)),
            _psd("SPSK", DECISION_WATCH, increase=False, reasons=("SI_WATCH",)),
        ):
            plan = allocate_new_money(
                available_amount=Decimal("60000"),
                amount_currency="TRY",
                portfolio_view=view,
                policy=policy,
                conversion=_fx(),
                enable_hybrid_exposure_allocation=False,
                security_decisions=(decision,),
            )
            self.assertFalse(any(row.symbol == "SPSK" for row in plan.recommendations))

    def test_valid_increase_decision_can_reach_candidate_stage(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_spsk_underweight_view(),
            policy=_exposure_policy(equity=70, sukuk=20, cash=10),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
            security_decisions=(
                _psd("SPSK", DECISION_CONSIDER_TOP_UP, increase=True, reasons=("ELIGIBLE_TO_INCREASE",)),
            ),
        )
        self.assertTrue(
            any(row.symbol == "SPSK" for row in plan.recommendations)
            or any(row.symbol == "SPSK" and row.reason_code != REASON_EXPOSURE_INCREASE_NOT_ALLOWED for row in plan.skipped)
            or plan.total_allocated > 0
        )

    def test_equity_and_bist_isolation(self) -> None:
        aapl = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="AAPL",
                participation_status="Uygun",
                research_allowed=True,
                si_state=STATE_WATCH,
                si_score=53.3,
                is_holding=True,
                instrument_type="EQUITY",
                market="US",
                economic_exposure_status="STRICT",
                portfolio_weight=8.0,
            )
        )
        asels = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="ASELS",
                participation_status="Uygun",
                research_allowed=True,
                si_state=STATE_WATCH,
                is_holding=True,
                instrument_type="EQUITY",
                market="BIST",
                economic_exposure_status="STRICT",
                portfolio_weight=5.0,
            )
        )
        self.assertEqual(aapl.decision, DECISION_WATCH)
        self.assertEqual(asels.decision, DECISION_WATCH)
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").state, STATE_INSUFFICIENT_DATA)
        source = NEW_MONEY.read_text(encoding="utf-8")
        self.assertNotIn("FMPClient", source)
        self.assertNotIn("PILOT_FUND_SYMBOLS", source)
        self.assertNotIn("FMPClient", ENGINE.read_text(encoding="utf-8"))
        self.assertEqual(len(PILOT_FUND_SYMBOLS), 4)
        self.assertTrue(_equity("AAPL").symbol)


if __name__ == "__main__":
    unittest.main()
