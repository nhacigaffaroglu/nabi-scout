from __future__ import annotations

import math
import unittest
from datetime import date, timedelta
from pathlib import Path

from services.fund_decision_readiness import evaluate_official_fund_decision
from services.fund_intelligence_engine import (
    evaluate_fund_intelligence,
    evaluate_official_fund_intelligence,
    weights_for_profile,
)
from services.fund_product_contract import (
    DIM_CONCENTRATION_EVAL,
    DIM_COST_EVAL,
    DIM_DIVERSIFICATION_EVAL,
    DIM_ISSUER_CONCENTRATION,
    DIM_LIQUIDITY_EVAL,
    DIM_MATURITY,
    DIM_MOMENTUM_EVAL,
    DIM_PARTICIPATION_MANDATE,
    DIM_PERFORMANCE_EVAL,
    DIM_RISK_EVAL,
    DIM_STATUS_MISSING,
    DIM_STATUS_NOT_APPLICABLE,
    DIM_STATUS_READY,
    EQUITY_PARTICIPATION_FUND_WEIGHTS,
    LIQUIDITY_PARTICIPATION_FUND_WEIGHTS,
    PILOT_FUND_SYMBOLS,
    PILOT_TEFAS_FUND_CODES,
    PROFILE_EQUITY_PARTICIPATION_FUND,
    PROFILE_LIQUIDITY_PARTICIPATION_FUND,
    PROFILE_SUKUK_PARTICIPATION_FUND,
    RISK_FACT_HISTORICAL_MAX_DRAWDOWN,
    RISK_FACT_HISTORICAL_VOLATILITY,
    RISK_FACT_OFFICIAL_RISK_VALUE,
    SUKUK_PARTICIPATION_FUND_WEIGHTS,
    TEFAS_LOOKBACK_RULE,
    TEFAS_VOLATILITY_CONVENTION,
    TefasPriceObservation,
    TefasPriceSeries,
)
from services.official_kap_pdr import (
    issuer_concentration_stats,
    pdr_lookthrough_readiness,
    weighted_average_maturity_days,
)
from services.official_kap_pdr_evidence import load_captured_pdr_holdings
from services.official_tefas_performance import (
    TRADING_DAYS_PER_YEAR,
    add_calendar_months,
    annualized_volatility_pct,
    calendar_gap_is_zero_return,
    daily_simple_returns,
    maximum_drawdown,
    observation_on_or_before,
    performance_from_tefas_series,
    series_reliability,
    trailing_unit_price_return,
    weekend_zero_return_injected,
    ytd_unit_price_return,
)
from services.official_tefas_product import default_tefas_fund_provider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import DECISION_WATCH
from services.wealth_new_money_allocation import allocate_new_money


ENGINE = Path("services/fund_intelligence_engine.py")
TEFAS = Path("services/official_tefas_product.py")
BIST = Path("services/bist_refresh_contract.py")
US_SI = Path("services/security_intelligence_engine.py")
EIGHT_E = Path("services/portfolio_security_decision_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
CONTRACT = Path("services/fund_product_contract.py")


def _obs(day: str, price: float, code: str = "AIS") -> TefasPriceObservation:
    return TefasPriceObservation(date=day, price=price, fund_code=code)


def _series(rows: list[TefasPriceObservation], *, code: str = "AIS") -> TefasPriceSeries:
    ordered = tuple(sorted(rows, key=lambda item: item.date))
    return TefasPriceSeries(
        fund_code=code,
        first_date=ordered[0].date if ordered else None,
        last_date=ordered[-1].date if ordered else None,
        observation_count=len(ordered),
        duplicate_dates=(),
        missing_dates=(),
        weekday_gaps=(),
        price_field="fiyat",
        price_semantics="TEFAS_UNIT_PRICE",
        source="tefas",
        source_url="https://www.tefas.gov.tr/api/funds/fonFiyatBilgiGetir",
        period_months=12,
        observations=ordered,
    )


def _weekday_climb(*, start: date, sessions: int, start_price: float = 100.0) -> TefasPriceSeries:
    rows: list[TefasPriceObservation] = []
    cursor = start
    price = start_price
    while len(rows) < sessions:
        if cursor.weekday() < 5:
            rows.append(_obs(cursor.isoformat(), round(price, 6)))
            price *= 1.001
        cursor += timedelta(days=1)
    return _series(rows)


class TefasTrailingReturnTests(unittest.TestCase):
    def test_previous_valid_observation_skips_weekend(self) -> None:
        series = _series(
            [
                _obs("2026-08-21", 100.0),
                _obs("2026-08-24", 101.0),
                _obs("2026-08-28", 102.0),
            ]
        )
        friday = observation_on_or_before(series.observations, date(2026, 8, 23))
        self.assertIsNotNone(friday)
        assert friday is not None
        self.assertEqual(friday.date, "2026-08-21")
        self.assertEqual(friday.price, 100.0)
        self.assertEqual(TEFAS_LOOKBACK_RULE, "PREVIOUS_VALID_OBSERVATION")

    def test_calendar_month_lookback_and_ytd(self) -> None:
        rows = []
        cursor = date(2025, 12, 31)
        price = 100.0
        while cursor <= date(2026, 8, 28):
            if cursor.weekday() < 5:
                rows.append(_obs(cursor.isoformat(), price))
                price += 0.1
            cursor += timedelta(days=1)
        series = _series(rows)
        one_m = trailing_unit_price_return(series, months=1)
        self.assertIsNotNone(one_m)
        end = series.observations[-1]
        start = observation_on_or_before(
            series.observations, add_calendar_months(date.fromisoformat(end.date), -1)
        )
        assert start is not None
        self.assertEqual(one_m, round((end.price / start.price - 1.0) * 100.0, 2))
        ytd = ytd_unit_price_return(series)
        prior = [row for row in series.observations if row.date.startswith("2025")][-1]
        self.assertEqual(ytd, round((end.price / prior.price - 1.0) * 100.0, 2))

    def test_no_weekend_zero_returns_and_sqrt_252(self) -> None:
        series = _series(
            [
                _obs("2026-08-21", 100.0),
                _obs("2026-08-24", 102.0),
            ]
        )
        daily = daily_simple_returns(series.observations)
        self.assertEqual(len(daily), 1)
        self.assertAlmostEqual(daily[0], 0.02, places=10)
        self.assertFalse(weekend_zero_return_injected(series.observations))
        self.assertTrue(calendar_gap_is_zero_return(series, date(2026, 8, 22)))
        self.assertEqual(TEFAS_VOLATILITY_CONVENTION, "SQRT_252")
        self.assertEqual(TRADING_DAYS_PER_YEAR, 252)
        climb = _weekday_climb(start=date(2025, 8, 28), sessions=80, start_price=10.0)
        vol = annualized_volatility_pct(climb.observations)
        self.assertIsNotNone(vol)
        returns = daily_simple_returns(climb.observations)
        mean = sum(returns) / len(returns)
        stdev = math.sqrt(sum((item - mean) ** 2 for item in returns) / (len(returns) - 1))
        self.assertEqual(vol, round(stdev * math.sqrt(252) * 100.0, 2))

    def test_max_drawdown_peak_trough(self) -> None:
        series = _series(
            [_obs((date(2026, 1, 1) + timedelta(days=i)).isoformat(), price) for i, price in enumerate(
                [10.0] * 10 + [20.0, 19.0, 18.0, 12.0] + [13.0] * 20
            )]
        )
        drawdown, peak, trough = maximum_drawdown(series.observations)
        self.assertEqual(drawdown, -40.0)
        self.assertEqual(peak, series.observations[10].date)
        self.assertEqual(trough, series.observations[13].date)

    def test_official_risk_value_is_not_historical_risk(self) -> None:
        series = _weekday_climb(start=date(2025, 8, 28), sessions=80)
        view = performance_from_tefas_series(series, official_risk_value="1")
        self.assertEqual(view.official_risk_value, "1")
        self.assertIsNotNone(view.volatility)
        self.assertIsNotNone(view.drawdown)
        self.assertNotEqual(str(view.volatility), "1")
        self.assertEqual(view.volatility_convention, TEFAS_VOLATILITY_CONVENTION)


class TurkishProfileWeightTests(unittest.TestCase):
    def test_weights_sum_to_one_and_were_declared_in_contract(self) -> None:
        source = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("Defined from mandate economics, not pilot scores", source)
        for weights in (
            LIQUIDITY_PARTICIPATION_FUND_WEIGHTS,
            EQUITY_PARTICIPATION_FUND_WEIGHTS,
            SUKUK_PARTICIPATION_FUND_WEIGHTS,
        ):
            self.assertAlmostEqual(sum(weights.values()), 1.0, places=10)
        self.assertEqual(
            weights_for_profile(PROFILE_LIQUIDITY_PARTICIPATION_FUND),
            dict(LIQUIDITY_PARTICIPATION_FUND_WEIGHTS),
        )
        self.assertNotIn(DIM_LIQUIDITY_EVAL, LIQUIDITY_PARTICIPATION_FUND_WEIGHTS)
        self.assertNotIn(DIM_MOMENTUM_EVAL, LIQUIDITY_PARTICIPATION_FUND_WEIGHTS)
        self.assertNotIn(DIM_MOMENTUM_EVAL, SUKUK_PARTICIPATION_FUND_WEIGHTS)
        self.assertIn(DIM_MOMENTUM_EVAL, EQUITY_PARTICIPATION_FUND_WEIGHTS)
        self.assertIn(DIM_MATURITY, LIQUIDITY_PARTICIPATION_FUND_WEIGHTS)
        self.assertIn(DIM_ISSUER_CONCENTRATION, SUKUK_PARTICIPATION_FUND_WEIGHTS)


class TurkishFundIntelligenceTests(unittest.TestCase):
    def test_profiles_performance_risk_and_holdings(self) -> None:
        provider = default_tefas_fund_provider()
        expected = {
            "AIS": PROFILE_LIQUIDITY_PARTICIPATION_FUND,
            "ZPE": PROFILE_EQUITY_PARTICIPATION_FUND,
            "IAT": PROFILE_SUKUK_PARTICIPATION_FUND,
        }
        for code in PILOT_TEFAS_FUND_CODES:
            series = provider.price_history(code, period_months=12)
            self.assertEqual(series.first_date, "2025-08-28")
            self.assertEqual(series.last_date, "2026-08-28")
            self.assertEqual(series.observation_count, 252)
            self.assertEqual(series.duplicate_dates, ())
            self.assertEqual(series_reliability(series), "HIGH")
            view = evaluate_official_fund_intelligence(code)
            self.assertEqual(view.fund_type_profile, expected[code])
            evidence = view.evidence_map()
            self.assertEqual(evidence[DIM_PERFORMANCE_EVAL], DIM_STATUS_READY)
            self.assertEqual(evidence[DIM_RISK_EVAL], DIM_STATUS_READY)
            self.assertEqual(evidence[DIM_COST_EVAL], DIM_STATUS_READY)
            self.assertEqual(evidence[DIM_DIVERSIFICATION_EVAL], DIM_STATUS_READY)
            self.assertEqual(evidence[DIM_CONCENTRATION_EVAL], DIM_STATUS_READY)
            self.assertEqual(evidence[DIM_LIQUIDITY_EVAL], DIM_STATUS_MISSING)
            self.assertEqual(view.dimension(DIM_COST_EVAL).facts_used, ("kap_management_fee",))
            risk = view.dimension(DIM_RISK_EVAL)
            self.assertIn(RISK_FACT_HISTORICAL_MAX_DRAWDOWN, risk.facts_used)
            self.assertIn(RISK_FACT_HISTORICAL_VOLATILITY, risk.facts_used)
            self.assertIn(RISK_FACT_OFFICIAL_RISK_VALUE, risk.facts_used)
            self.assertNotEqual(str(view.dimension(DIM_RISK_EVAL).score), provider.official_risk_value(code))
            self.assertGreaterEqual(view.completeness, 0.55)
            self.assertIsNotNone(view.score)
            self.assertTrue(view.participation.eligible)
            self.assertTrue(view.publishable)
            generic = view.generic_intelligence()
            self.assertEqual(generic["si_state"], view.state)
            self.assertEqual(generic["si_score"], view.score)
            self.assertEqual(provider.sharia_evidence(code).participation_status, PARTICIPATION_STATUS_UYGUN)

    def test_profile_specific_dimensions(self) -> None:
        ais = evaluate_official_fund_intelligence("AIS")
        zpe = evaluate_official_fund_intelligence("ZPE")
        iat = evaluate_official_fund_intelligence("IAT")
        self.assertEqual(ais.evidence_map()[DIM_MATURITY], DIM_STATUS_READY)
        self.assertEqual(ais.evidence_map()[DIM_ISSUER_CONCENTRATION], DIM_STATUS_NOT_APPLICABLE)
        self.assertIsNone(ais.dimension(DIM_MOMENTUM_EVAL))
        self.assertEqual(zpe.evidence_map()[DIM_MOMENTUM_EVAL], DIM_STATUS_READY)
        self.assertEqual(zpe.dimension(DIM_MOMENTUM_EVAL).facts_used, ("return_3m",))
        self.assertEqual(zpe.evidence_map()[DIM_MATURITY], DIM_STATUS_NOT_APPLICABLE)
        self.assertEqual(iat.evidence_map()[DIM_MATURITY], DIM_STATUS_READY)
        self.assertEqual(iat.evidence_map()[DIM_ISSUER_CONCENTRATION], DIM_STATUS_READY)
        self.assertIsNone(iat.dimension(DIM_MOMENTUM_EVAL))
        self.assertEqual(ais.dimension(DIM_PERFORMANCE_EVAL).facts_used, ("return_1y",))
        self.assertEqual(provider_fee("AIS"), 0.85)
        self.assertEqual(provider_fee("ZPE"), 2.75)
        self.assertEqual(provider_fee("IAT"), 1.75)

    def test_holdings_maturity_issuer_and_no_inferred_fields(self) -> None:
        ais = load_captured_pdr_holdings("AIS")
        zpe = load_captured_pdr_holdings("ZPE")
        iat = load_captured_pdr_holdings("IAT")
        self.assertTrue(pdr_lookthrough_readiness(ais).maturity_ready)
        self.assertTrue(pdr_lookthrough_readiness(iat).issuer_concentration_ready)
        self.assertIsNotNone(weighted_average_maturity_days(ais))
        largest, top10, count = issuer_concentration_stats(iat)
        self.assertIsNotNone(largest)
        self.assertGreater(count, 1)
        self.assertGreater(top10 or 0.0, largest or 0.0)
        engine = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("credit rating", engine.lower())
        self.assertNotIn("property type", engine.lower())
        _ = zpe

    def test_missing_dimension_does_not_redistribute(self) -> None:
        view = evaluate_official_fund_intelligence("AIS")
        ready_weighted = [
            name
            for name, weight in LIQUIDITY_PARTICIPATION_FUND_WEIGHTS.items()
            if view.dimension(name) is not None and view.dimension(name).status == DIM_STATUS_READY
        ]
        self.assertEqual(set(ready_weighted), set(LIQUIDITY_PARTICIPATION_FUND_WEIGHTS))
        self.assertEqual(view.completeness, 1.0)
        self.assertNotIn(DIM_LIQUIDITY_EVAL, LIQUIDITY_PARTICIPATION_FUND_WEIGHTS)
        provider = default_tefas_fund_provider()
        partial = evaluate_fund_intelligence(
            facts=provider.facts("AIS"),
            mandate=provider.mandate("AIS"),
            sharia=provider.sharia_evidence("AIS"),
            purification=provider.purification_evidence("AIS"),
            lookthrough=None,
            performance=provider.performance("AIS"),
            maturity_ready=True,
            maturity_days=20.0,
        )
        self.assertEqual(partial.evidence_map()[DIM_DIVERSIFICATION_EVAL], DIM_STATUS_MISSING)
        self.assertEqual(partial.evidence_map()[DIM_CONCENTRATION_EVAL], DIM_STATUS_MISSING)
        self.assertAlmostEqual(partial.completeness, 0.75, places=4)
        self.assertIsNotNone(partial.score)
        self.assertNotEqual(partial.score, view.score)

    def test_participation_firewall_and_eight_e_new_money(self) -> None:
        frozen = {"AIS": (70.39, "WATCH"), "ZPE": (66.32, "WATCH"), "IAT": (60.49, "NEUTRAL")}
        for code in PILOT_TEFAS_FUND_CODES:
            view = evaluate_official_fund_intelligence(code)
            self.assertEqual(view.dimension(DIM_PARTICIPATION_MANDATE).status, DIM_STATUS_READY)
            self.assertNotIn("PARTICIPATION_KONTROL_ET", view.dimension(DIM_PARTICIPATION_MANDATE).reason_codes)
            self.assertTrue(view.participation.eligible)
            self.assertTrue(view.publishable)
            self.assertEqual(view.score, frozen[code][0])
            self.assertEqual(view.state, frozen[code][1])
            decision = evaluate_official_fund_decision(code)
            self.assertEqual(decision.decision, DECISION_WATCH)
            self.assertFalse(decision.exposure_increase_allowed)
        source = TEFAS.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_official_fund_decision", source)
        self.assertNotIn("allocate_new_money", source)
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertTrue(callable(allocate_new_money))

    def test_sp_funds_bist_us_isolation(self) -> None:
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPUS").state, "WATCH")
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").state, "WATCH")
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").state, "NEUTRAL")
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").state, "NEUTRAL")
        provider = default_tefas_fund_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertFalse(provider.supports(symbol))
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertTrue(US_SI.is_file())
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        self.assertNotIn("evaluate_official_fund_intelligence", EIGHT_E.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))


def provider_fee(code: str) -> float:
    return default_tefas_fund_provider().facts(code).expense_ratio


if __name__ == "__main__":
    unittest.main()
