from __future__ import annotations

import unittest
from pathlib import Path

from services.hybrid_exposure_allocation_policy import HybridPortfolioMode
from services.kap_eps_normalization import BASIS_UNRESOLVED, asels_anomaly_classification
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_security_decision_contract import (
    DECISION_AVOID,
    DECISION_CONSIDER_NEW_POSITION,
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_INSUFFICIENT_DATA,
    DECISION_REDUCE,
    DECISION_REVIEW,
    DECISION_WATCH,
    INCREASE_DECISIONS,
    PORTFOLIO_SECURITY_DECISIONS,
    PortfolioSecurityContext,
    REASON_CONCENTRATION_LIMIT,
    REASON_ECONOMIC_EXPOSURE_UNAVAILABLE,
    REASON_ELIGIBLE_TO_INCREASE,
    REASON_PARTICIPATION_MISSING,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_PORTFOLIO_CONTEXT_MISSING,
    REASON_SI_AVOID,
    REASON_SI_CAUTION,
    REASON_SI_INSUFFICIENT,
    REASON_SI_MISSING,
    REASON_SI_WATCH,
    REASON_UNSUPPORTED_INSTRUMENT,
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
    STATE_NEUTRAL,
    STATE_WATCH,
)
from services.security_master_contract import (
    INSTRUMENT_CASH,
    INSTRUMENT_EQUITY,
    INSTRUMENT_ETF,
    INSTRUMENT_SUKUK,
    INSTRUMENT_UNKNOWN,
)
from services.security_master_service import SecurityMasterService
from services.wealth_contract import ASSET_CLASS_FUND, CASH_SYMBOL


ENGINE = Path("services/portfolio_security_decision_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
FIXTURE_BIST = "EQBISTX"
PILOTS = ("ASELS", "BIMAS", "TUPRS")
REAL_QTY = {"ASELS": 680.0, "BIMAS": 1594.0, "TUPRS": 1032.0}


def _ctx(**overrides) -> PortfolioSecurityContext:
    payload = dict(
        symbol="EQBISTX",
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        si_state=STATE_WATCH,
        si_score=53.6,
        si_confidence=0.8,
        si_data_quality="STRONG",
        si_as_of="2026-08-28",
        is_holding=False,
        concentration_ceiling=CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
        economic_exposure_status=HybridPortfolioMode.STRICT.value,
        instrument_type=INSTRUMENT_EQUITY,
        market="BIST",
        research_status="INCELEMEDE",
        candidate_exists=True,
        as_of="2026-08-28",
    )
    payload.update(overrides)
    return PortfolioSecurityContext(**payload)


def _holding(symbol: str, **overrides) -> PortfolioSecurityContext:
    qty = REAL_QTY[symbol]
    payload = dict(
        symbol=symbol,
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        is_holding=True,
        quantity=qty,
        market_value=qty * 400.0,
        portfolio_weight=8.0,
        concentration_ceiling=CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
        economic_exposure_status=HybridPortfolioMode.STRICT.value,
        instrument_type=INSTRUMENT_EQUITY,
        market="TR",
        as_of="2026-08-28",
    )
    payload.update(overrides)
    return PortfolioSecurityContext(**payload)


def _us(**overrides) -> PortfolioSecurityContext:
    payload = dict(
        symbol="CRM",
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        si_state=STATE_ATTRACTIVE,
        si_score=72.0,
        si_confidence=0.8,
        si_data_quality="STRONG",
        si_as_of="2026-08-29",
        is_holding=True,
        quantity=10.0,
        market_value=2500.0,
        portfolio_weight=5.0,
        concentration_ceiling=CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
        economic_exposure_status=HybridPortfolioMode.STRICT.value,
        instrument_type=INSTRUMENT_EQUITY,
        market="US",
        as_of="2026-08-29",
    )
    payload.update(overrides)
    return PortfolioSecurityContext(**payload)


class BistEquitySupportTests(unittest.TestCase):
    def test_generic_bist_equity_is_supported(self) -> None:
        for market in ("BIST", "TR", "IST", "XIST", "ISTANBUL"):
            self.assertTrue(
                supports_portfolio_decision(
                    instrument_type=INSTRUMENT_EQUITY,
                    market=market,
                    symbol=FIXTURE_BIST,
                ),
                market,
            )
        self.assertTrue(
            supports_portfolio_decision(
                instrument_type=INSTRUMENT_EQUITY,
                market="US",
                symbol="AAPL",
            )
        )

    def test_no_symbol_allowlist(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("supports_portfolio_decision", source)
        self.assertNotIn("if symbol in BIST_PORTFOLIO_SYMBOLS", source)
        self.assertNotIn('"ASELS"', source)
        self.assertNotIn('"BIMAS"', source)
        self.assertNotIn('"TUPRS"', source)
        self.assertTrue(
            supports_portfolio_decision(
                instrument_type=INSTRUMENT_EQUITY,
                market="BIST",
                symbol=FIXTURE_BIST,
            )
        )
        self.assertTrue(
            supports_portfolio_decision(
                instrument_type=INSTRUMENT_EQUITY,
                market="BIST",
                symbol="UNKNOWNBIST",
            )
        )

    def test_pilots_are_no_longer_unsupported_instrument(self) -> None:
        for symbol, state, score in (
            ("ASELS", STATE_NEUTRAL, 53.6),
            ("BIMAS", STATE_CAUTION, 43.7),
            ("TUPRS", STATE_AVOID, 29.7),
        ):
            result = evaluate_portfolio_security_decision(
                _holding(symbol, si_state=state, si_score=score)
            )
            self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
            self.assertNotEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertIn(result.decision, PORTFOLIO_SECURITY_DECISIONS)

    def test_no_bist_specific_decision_vocabulary(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("BIST_WATCH", source)
        self.assertNotIn("BIST_AVOID", source)
        self.assertNotIn("BIST_ONLY", source)
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_NEUTRAL, si_score=53.6)
        )
        self.assertIn(result.decision, PORTFOLIO_SECURITY_DECISIONS)


class ParticipationFirewallTests(unittest.TestCase):
    def test_uygun_may_proceed_to_8e(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_NEUTRAL, si_score=53.6)
        )
        self.assertEqual(result.participation_status, PARTICIPATION_STATUS_UYGUN)
        self.assertNotIn(REASON_PARTICIPATION_NOT_UYGUN, result.blocking_reasons)
        self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)

    def test_kontrol_et_cannot_increase(self) -> None:
        held = evaluate_portfolio_security_decision(
            _holding(
                "ASELS",
                si_state=STATE_ATTRACTIVE,
                participation_status=PARTICIPATION_STATUS_KONTROL_ET,
            )
        )
        fresh = evaluate_portfolio_security_decision(
            _ctx(
                si_state=STATE_ATTRACTIVE,
                participation_status=PARTICIPATION_STATUS_KONTROL_ET,
            )
        )
        self.assertEqual(held.decision, DECISION_REVIEW)
        self.assertEqual(fresh.decision, DECISION_REVIEW)
        self.assertFalse(held.exposure_increase_allowed)
        self.assertFalse(fresh.exposure_increase_allowed)
        self.assertIn(REASON_PARTICIPATION_NOT_UYGUN, held.blocking_reasons)

    def test_uygun_degil_fail_closed(self) -> None:
        held = evaluate_portfolio_security_decision(
            _holding(
                "TUPRS",
                si_state=STATE_ATTRACTIVE,
                participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL,
            )
        )
        fresh = evaluate_portfolio_security_decision(
            _ctx(
                si_state=STATE_ATTRACTIVE,
                participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL,
            )
        )
        self.assertEqual(held.decision, DECISION_HOLD)
        self.assertEqual(fresh.decision, DECISION_AVOID)
        self.assertFalse(held.exposure_increase_allowed)
        self.assertFalse(fresh.exposure_increase_allowed)

    def test_missing_participation_fail_closed(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_NEUTRAL, participation_status=None)
        )
        self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_PARTICIPATION_MISSING, result.blocking_reasons)


class SiMappingAndHoldingTests(unittest.TestCase):
    def test_avoid_cannot_increase_exposure(self) -> None:
        held = evaluate_portfolio_security_decision(
            _holding("TUPRS", si_state=STATE_AVOID, si_score=29.7)
        )
        fresh = evaluate_portfolio_security_decision(_ctx(si_state=STATE_AVOID))
        self.assertEqual(held.decision, DECISION_HOLD)
        self.assertEqual(fresh.decision, DECISION_AVOID)
        self.assertFalse(held.exposure_increase_allowed)
        self.assertFalse(fresh.exposure_increase_allowed)
        self.assertNotIn(held.decision, INCREASE_DECISIONS)
        self.assertIn(REASON_SI_AVOID, held.blocking_reasons)

    def test_caution_does_not_increase_because_held(self) -> None:
        held = evaluate_portfolio_security_decision(
            _holding("BIMAS", si_state=STATE_CAUTION, si_score=43.7)
        )
        fresh = evaluate_portfolio_security_decision(_ctx(si_state=STATE_CAUTION))
        self.assertEqual(held.decision, DECISION_REVIEW)
        self.assertEqual(fresh.decision, DECISION_WATCH)
        self.assertFalse(held.exposure_increase_allowed)
        self.assertFalse(fresh.exposure_increase_allowed)
        self.assertIn(REASON_SI_CAUTION, held.blocking_reasons)

    def test_watch_existing_holding_is_watch_not_top_up(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_WATCH, si_score=53.6)
        )
        self.assertEqual(result.decision, DECISION_WATCH)
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_SI_WATCH, result.blocking_reasons)
        self.assertNotEqual(result.decision, DECISION_CONSIDER_TOP_UP)

    def test_neutral_existing_holding_is_watch(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_NEUTRAL, si_score=53.6)
        )
        self.assertEqual(result.decision, DECISION_WATCH)
        self.assertFalse(result.exposure_increase_allowed)

    def test_insufficient_data_fail_closed(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_INSUFFICIENT_DATA)
        )
        missing = evaluate_portfolio_security_decision(_holding("ASELS", si_state=None))
        self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
        self.assertEqual(missing.decision, DECISION_INSUFFICIENT_DATA)
        self.assertIn(REASON_SI_INSUFFICIENT, result.blocking_reasons)
        self.assertIn(REASON_SI_MISSING, missing.blocking_reasons)
        self.assertFalse(result.exposure_increase_allowed)

    def test_existing_holding_path_uses_real_quantities(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_NEUTRAL, si_score=53.6)
        )
        self.assertEqual(result.symbol, "ASELS")
        self.assertTrue(result.research_allowed)
        self.assertFalse(result.exposure_increase_allowed)

    def test_non_holding_states(self) -> None:
        attractive = evaluate_portfolio_security_decision(
            _ctx(si_state=STATE_ATTRACTIVE)
        )
        watch = evaluate_portfolio_security_decision(_ctx(si_state=STATE_WATCH))
        caution = evaluate_portfolio_security_decision(_ctx(si_state=STATE_CAUTION))
        avoid = evaluate_portfolio_security_decision(_ctx(si_state=STATE_AVOID))
        missing = evaluate_portfolio_security_decision(
            _ctx(si_state=STATE_INSUFFICIENT_DATA)
        )
        self.assertEqual(attractive.decision, DECISION_CONSIDER_NEW_POSITION)
        self.assertTrue(attractive.exposure_increase_allowed)
        self.assertEqual(watch.decision, DECISION_WATCH)
        self.assertEqual(caution.decision, DECISION_WATCH)
        self.assertEqual(avoid.decision, DECISION_AVOID)
        self.assertEqual(missing.decision, DECISION_INSUFFICIENT_DATA)
        for result in (watch, caution, avoid, missing):
            self.assertFalse(result.exposure_increase_allowed)
            self.assertNotEqual(result.decision, DECISION_CONSIDER_TOP_UP)

    def test_concentration_guard(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding(
                "ASELS",
                si_state=STATE_ATTRACTIVE,
                portfolio_weight=21.0,
            )
        )
        self.assertEqual(result.decision, DECISION_REDUCE)
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_CONCENTRATION_LIMIT, result.blocking_reasons)

    def test_missing_price_or_weight_on_holding(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding(
                "ASELS",
                si_state=STATE_NEUTRAL,
                market_value=None,
                portfolio_weight=None,
            )
        )
        self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_PORTFOLIO_CONTEXT_MISSING, result.blocking_reasons)

    def test_missing_identity_and_invalid_bist(self) -> None:
        missing_instrument = evaluate_portfolio_security_decision(
            _ctx(instrument_type=None, market="BIST", si_state=STATE_ATTRACTIVE)
        )
        unknown = evaluate_portfolio_security_decision(
            _ctx(
                instrument_type=INSTRUMENT_UNKNOWN,
                market="BIST",
                si_state=STATE_ATTRACTIVE,
            )
        )
        self.assertFalse(supports_portfolio_decision(instrument_type=None, market="BIST"))
        self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, missing_instrument.blocking_reasons)
        self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, unknown.blocking_reasons)
        self.assertFalse(missing_instrument.exposure_increase_allowed)

    def test_missing_portfolio_context(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding(
                "ASELS",
                si_state=STATE_NEUTRAL,
                economic_exposure_status=None,
            )
        )
        self.assertEqual(result.decision, DECISION_REVIEW)
        self.assertFalse(result.exposure_increase_allowed)
        self.assertIn(REASON_ECONOMIC_EXPOSURE_UNAVAILABLE, result.blocking_reasons)


class AselsEpsExceptionTests(unittest.TestCase):
    def test_asels_eps_remains_unresolved_and_8e_still_usable(self) -> None:
        self.assertEqual(asels_anomaly_classification(656.79), BASIS_UNRESOLVED)
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_NEUTRAL, si_score=53.6)
        )
        self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
        self.assertEqual(result.decision, DECISION_WATCH)
        self.assertEqual(result.security_intelligence_state, STATE_NEUTRAL)


class UsParityAndUnsupportedTests(unittest.TestCase):
    def test_aapl_parity(self) -> None:
        result = evaluate_portfolio_security_decision(_us(symbol="AAPL"))
        self.assertEqual(result.decision, DECISION_CONSIDER_TOP_UP)
        self.assertTrue(result.exposure_increase_allowed)
        self.assertIn(REASON_ELIGIBLE_TO_INCREASE, result.reason_codes)
        self.assertEqual(result.participation_status, PARTICIPATION_STATUS_UYGUN)

    def test_crm_parity(self) -> None:
        result = evaluate_portfolio_security_decision(_us())
        self.assertEqual(result.decision, DECISION_CONSIDER_TOP_UP)
        self.assertTrue(result.exposure_increase_allowed)
        self.assertEqual(result.security_intelligence_state, STATE_ATTRACTIVE)

    def test_us_avoid_and_insufficient_unchanged(self) -> None:
        avoid = evaluate_portfolio_security_decision(_us(si_state=STATE_AVOID))
        missing = evaluate_portfolio_security_decision(
            _us(si_state=STATE_INSUFFICIENT_DATA)
        )
        self.assertEqual(avoid.decision, DECISION_HOLD)
        self.assertFalse(avoid.exposure_increase_allowed)
        self.assertEqual(missing.decision, DECISION_INSUFFICIENT_DATA)
        self.assertIn(REASON_SI_INSUFFICIENT, missing.blocking_reasons)

    def test_unsupported_non_equity_unchanged(self) -> None:
        cases = (
            _ctx(symbol=CASH_SYMBOL, instrument_type=INSTRUMENT_CASH, market="TR"),
            _ctx(symbol="TF_KATILIM", instrument_type=INSTRUMENT_SUKUK, market="TR"),
        )
        for ctx in cases:
            result = evaluate_portfolio_security_decision(ctx)
            self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons, ctx.symbol)
            self.assertFalse(result.exposure_increase_allowed)
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)

    def test_no_new_money_sizing_or_persistence(self) -> None:
        result = evaluate_portfolio_security_decision(
            _holding("ASELS", si_state=STATE_NEUTRAL, si_score=53.6)
        )
        payload = result.to_dict()
        self.assertIsNone(payload.get("allocated_amount"))
        self.assertNotIn("buy_amount", payload)
        self.assertNotIn("share_quantity", payload)
        engine = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("allocate_new_money", engine)
        self.assertNotIn(".insert(", engine)
        self.assertNotIn(".upsert(", engine)
        self.assertNotIn("append_snapshot", engine)
        new_money = NEW_MONEY.read_text(encoding="utf-8")
        self.assertIn("security_decisions", new_money)
        self.assertIn("exposure_increase_allowed", new_money)

    def test_security_master_identity_is_bist_equity(self) -> None:
        master = SecurityMasterService()
        for symbol in PILOTS:
            resolution = master.resolve_security(symbol)
            self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)
            self.assertTrue(
                supports_portfolio_decision(
                    instrument_type=resolution.instrument_type,
                    market="TR",
                    symbol=symbol,
                )
            )


if __name__ == "__main__":
    unittest.main()
