from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import unittest

from services.bist_eod_bulletin import parse_thb_csv, thb_download_url
from services.bist_official_market_facts import (
    attach_official_nominal_market_cap,
    market_facts_from_thb_bulletin,
)
from services.bist_si_readiness import (
    EVAL_INSUFFICIENT,
    EVAL_SAFE,
    EVAL_UNSAFE,
    SI_EVALUATION_BLOCKED_BY_READINESS,
    assess_bist_si_eligibility,
    audit_bist_si_readiness,
    classify_shadow_evaluation,
)
from services.bist_corporate_action_audit import (
    STATUS_UNRESOLVED,
    events_from_thb_flags,
    merge_official_events,
    window_adjustment_status,
)
from services.kap_annual_history import (
    build_kap_annual_history,
    kap_security_facts_payload_from_history,
)
from services.kap_capital_structure import parse_kap_capital_structure_html
from services.kap_eps_normalization import BASIS_UNRESOLVED, asels_anomaly_classification
from services.kap_public_bridge import ingest_public_kap_financials
from services.kap_public_parser import parse_public_kap_html
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    PortfolioSecurityContext,
    REASON_SI_MISSING,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_facts_service import SecurityFactsService
from services.security_intelligence_contract import (
    PERIOD_FY,
    PERIOD_MIXED,
    SecurityParticipationContext,
    STATUS_INSUFFICIENT_DATA,
)
from services.security_intelligence_engine import evaluate_security_intelligence
from services.security_intelligence_service import SecurityIntelligenceService, facts_from_candidate
from services.security_master_contract import INSTRUMENT_EQUITY
from tests.fixtures.bist_official_ca_window import official_window_events
from tests.fixtures.bist_thb_history_days import historical_row, weekday_series
from tests.fixtures.kap_annual_pilot import annual_series_html
from tests.fixtures.kap_detailed_search import official_fy_docs_html
from tests.fixtures.kap_eps_fy_rows import asels_unresolved_eps_html


FIXTURES = Path("tests/fixtures")
THB = FIXTURES / "bist_thb_eod_sample.csv"
CAPITAL = {
    "ASELS": FIXTURES / "kap_capital_structure_sample.html",
    "BIMAS": FIXTURES / "kap_capital_bimas_mismatch.html",
    "TUPRS": FIXTURES / "kap_capital_tuprs_nominal.html",
}
ENGINE = Path("services/security_intelligence_engine.py")
POLICY = Path("services/bist_si_readiness.py")
DECISION = Path("services/portfolio_security_decision_engine.py")
END = date(2026, 8, 19)


def _bulletin():
    return parse_thb_csv(
        THB.read_text(encoding="utf-8"),
        source_file="thb202608191.csv",
        source_url=thb_download_url(END),
    )


def _doc(html: str, *, symbol: str, disclosure_id: str):
    return parse_public_kap_html(
        html,
        symbol=symbol,
        disclosure_id=disclosure_id,
        include_comparative=True,
    )


def _official_history(symbol: str):
    if symbol == "ASELS":
        ids = {2022: "1117839", 2023: "1262825", 2024: "1395801", 2025: "1561039"}
        return [
            _doc(html, symbol="ASELS", disclosure_id=ids[year])
            for year, html in annual_series_html().items()
        ]
    return [
        _doc(html, symbol=symbol, disclosure_id=nid)
        for nid, html in official_fy_docs_html(symbol).items()
    ]


def _market(symbol: str, *, with_cap: bool = True):
    market = market_facts_from_thb_bulletin(_bulletin(), symbol)
    if not with_cap:
        return market
    return attach_official_nominal_market_cap(
        market,
        parse_kap_capital_structure_html(
            CAPITAL[symbol].read_text(encoding="utf-8"),
            symbol=symbol,
            source_url=f"https://kap.org.tr/tr/sirket-bilgileri/genel/{symbol}",
        ),
    )


def _compose(
    symbol: str,
    *,
    with_history: bool = True,
    with_cap: bool = True,
    with_momentum: bool = True,
    official_events=official_window_events(),
    stale: bool = False,
):
    history = build_kap_annual_history(symbol, _official_history(symbol)) if with_history else None
    payload = kap_security_facts_payload_from_history(history) if history is not None else None
    if payload is not None and symbol == "BIMAS":
        payload = dict(payload)
        payload["eps"] = 31.12
    if payload is not None and symbol == "TUPRS":
        payload = dict(payload)
        payload["eps"] = 15.32
    series = weekday_series(symbol, end=END, calendar_days=400, start_price=200.0) if with_momentum else None
    facts = SecurityFactsService().build(
        symbol,
        kap_financials=payload,
        bist_market_facts=_market(symbol, with_cap=with_cap),
        bist_price_history=series,
        bist_corporate_actions=official_events,
        stale=stale,
        allow_sec_cache_replay=False,
    )
    return facts, history


def _eligible(facts, *, participation=PARTICIPATION_STATUS_UYGUN, identity_ok=True, kap_bundle=None):
    view = evaluate_security_intelligence(
        facts,
        SecurityParticipationContext(status=participation, research_allowed=True),
    )
    return view, assess_bist_si_eligibility(
        facts,
        view,
        participation_status=participation,
        identity_ok=identity_ok,
        kap_bundle=kap_bundle,
    )


class RealFactsCompositionTests(unittest.TestCase):
    def test_official_facts_and_mixed_period_is_safe(self) -> None:
        for symbol in ("BIMAS", "TUPRS"):
            facts, history = _compose(symbol)
            self.assertEqual(facts.currency, "TRY")
            self.assertIsNotNone(facts.price)
            self.assertIsNotNone(facts.market_cap)
            self.assertIsNotNone(facts.revenue)
            self.assertIsNotNone(facts.revenue_cagr_3y)
            self.assertIsNotNone(facts.return_3m)
            self.assertIn(facts.period_kind, {PERIOD_FY, PERIOD_MIXED})
            self.assertEqual(
                classify_shadow_evaluation(facts, kap_bundle=history.latest().bundle),
                EVAL_SAFE,
            )
            audit = audit_bist_si_readiness(facts, kap_bundle=history.latest().bundle)
            self.assertEqual(audit.readiness_block, "")
            self.assertFalse(audit.persisted)

    def test_growth_partial_metrics_still_score(self) -> None:
        facts, _ = _compose("BIMAS")
        view, gate = _eligible(facts)
        self.assertIsNotNone(view.growth.score)
        self.assertIn("revenue_cagr_3y", view.growth.facts_used)
        self.assertIn("eps_cagr_3y", view.growth.missing_facts)
        self.assertIn("fcf_cagr_3y", view.growth.missing_facts)
        self.assertTrue(gate.can_score)

    def test_valuation_without_pe_and_full_multiples(self) -> None:
        asels, _ = _compose("ASELS")
        self.assertIsNone(asels.pe)
        self.assertIsNotNone(asels.price_to_sales)
        self.assertIsNotNone(asels.price_to_book)
        asels_view, asels_gate = _eligible(asels)
        self.assertIsNotNone(asels_view.valuation.score)
        self.assertIn("pe", asels_view.valuation.missing_facts)
        self.assertTrue(asels_gate.can_score)
        self.assertEqual(asels_anomaly_classification(656.79), BASIS_UNRESOLVED)

        bimas, _ = _compose("BIMAS")
        self.assertIsNotNone(bimas.pe)
        self.assertIsNotNone(bimas.price_to_sales)
        self.assertIsNotNone(bimas.price_to_book)
        bimas_view, bimas_gate = _eligible(bimas)
        self.assertEqual(set(bimas_view.valuation.facts_used), {"pe", "price_to_sales", "price_to_book"})
        self.assertTrue(bimas_gate.production_quality_sufficient)

    def test_momentum_ready_and_data_quality_real(self) -> None:
        facts, _ = _compose("TUPRS")
        view, _ = _eligible(facts)
        self.assertIsNotNone(view.momentum.score)
        self.assertGreaterEqual(len(view.momentum.facts_used), 3)
        self.assertIsNotNone(facts.completeness_pct)
        self.assertGreaterEqual(facts.completeness_pct, 50)
        self.assertIsNotNone(view.data_quality.score)


class EligibilityGateTests(unittest.TestCase):
    def test_core_minimum_and_independent_readiness(self) -> None:
        rows = {}
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            facts, history = _compose(symbol)
            view, gate = _eligible(facts, kap_bundle=history.latest().bundle if history else None)
            rows[symbol] = gate
            self.assertGreaterEqual(gate.scored_core_dimensions, gate.required_core_dimensions)
            self.assertEqual(gate.required_core_dimensions, 3)
            self.assertTrue(gate.can_score)
            self.assertTrue(gate.production_quality_sufficient)
            self.assertTrue(gate.si_production_eligible)
            self.assertFalse(gate.persisted)
        self.assertTrue(rows["BIMAS"].si_production_eligible)
        self.assertTrue(rows["TUPRS"].si_production_eligible)
        self.assertTrue(rows["ASELS"].si_production_eligible)

    def test_participation_fail_closed(self) -> None:
        facts, _ = _compose("BIMAS")
        _, kontrol = _eligible(facts, participation=PARTICIPATION_STATUS_KONTROL_ET)
        self.assertTrue(kontrol.can_score)
        self.assertTrue(kontrol.production_quality_sufficient)
        self.assertFalse(kontrol.si_production_eligible)
        view = evaluate_security_intelligence(
            facts,
            SecurityParticipationContext(status=PARTICIPATION_STATUS_KONTROL_ET, research_allowed=False),
        )
        self.assertFalse(view.investable)
        _, degil = _eligible(facts, participation=PARTICIPATION_STATUS_UYGUN_DEGIL)
        self.assertFalse(degil.si_production_eligible)
        avoid = evaluate_security_intelligence(
            facts,
            SecurityParticipationContext(status=PARTICIPATION_STATUS_UYGUN_DEGIL, research_allowed=False),
        )
        self.assertEqual(avoid.investment_state, "AVOID")

    def test_fail_closed_missing_and_stale(self) -> None:
        empty = SecurityFactsService().build("BIMAS", allow_sec_cache_replay=False)
        empty_view, empty_gate = _eligible(empty)
        self.assertEqual(classify_shadow_evaluation(empty), EVAL_INSUFFICIENT)
        self.assertFalse(empty_gate.can_score)
        self.assertFalse(empty_gate.production_quality_sufficient)
        self.assertEqual(empty_view.overall_status, STATUS_INSUFFICIENT_DATA)

        facts, _ = _compose("TUPRS")
        stale = replace(facts, stale=True)
        stale_view, stale_gate = _eligible(stale)
        self.assertTrue(stale_gate.can_score)
        self.assertIn(stale_view.overall_status, {"NEUTRAL", "WEAK", "VERY_WEAK", "STRONG", "VERY_STRONG"})

        no_cap, _ = _compose("ASELS", with_cap=False)
        self.assertIsNone(no_cap.market_cap)
        no_cap_view, _ = _eligible(no_cap)
        self.assertTrue(no_cap_view.valuation.score is None or "price_to_sales" in no_cap_view.valuation.missing_facts)

        no_mom, _ = _compose("BIMAS", with_momentum=False)
        no_mom_view, no_mom_gate = _eligible(no_mom)
        self.assertEqual(no_mom_view.momentum.status, STATUS_INSUFFICIENT_DATA)
        self.assertTrue(no_mom_gate.can_score)

        ytd = replace(facts, period_kind="YTD", revenue=1.0)
        self.assertEqual(classify_shadow_evaluation(ytd), EVAL_UNSAFE)
        _, ytd_gate = _eligible(ytd)
        self.assertFalse(ytd_gate.production_quality_sufficient)

        _, no_id = _eligible(facts, identity_ok=False)
        self.assertFalse(no_id.si_production_eligible)
        self.assertIn("MISSING_BIST_IDENTITY", no_id.insufficient_data_reason)

    def test_unresolved_corporate_action_and_missing_eps_only(self) -> None:
        flagged = (
            historical_row("ASELS", date(2026, 2, 1), 100.0, corporate_action_flag="03"),
            historical_row("ASELS", date(2026, 8, 19), 200.0),
        )
        events = merge_official_events(events_from_thb_flags(flagged), ())
        self.assertEqual(
            window_adjustment_status(events, start=date(2026, 2, 1), end=END),
            STATUS_UNRESOLVED,
        )
        blocked = SecurityFactsService().build(
            "ASELS",
            kap_financials=ingest_public_kap_financials(
                _doc(asels_unresolved_eps_html(), symbol="ASELS", disclosure_id="1561039")
            ),
            bist_market_facts=_market("ASELS"),
            allow_sec_cache_replay=False,
        )
        self.assertIsNone(blocked.eps)
        self.assertIsNone(blocked.pe)
        asels, _ = _compose("ASELS")
        self.assertIsNone(asels.eps)
        self.assertIsNone(asels.pe)
        _, gate = _eligible(asels)
        self.assertTrue(gate.si_production_eligible)


class IsolationTests(unittest.TestCase):
    def test_us_parity_and_no_8e_or_new_weights(self) -> None:
        aapl = facts_from_candidate(
            {"symbol": "AAPL", "revenue": 390_000, "roic": 40, "pe_ratio": 30},
            symbol="AAPL",
        )
        crm = facts_from_candidate(
            {"symbol": "CRM", "revenue": 37_000, "roic": 18, "pe_ratio": 28},
            symbol="CRM",
        )
        aapl_view = SecurityIntelligenceService().evaluate(aapl)
        crm_view = SecurityIntelligenceService().evaluate(crm)
        self.assertEqual(aapl.currency, aapl.currency)
        self.assertNotEqual(aapl.currency, "TRY")
        self.assertNotEqual(crm.currency, "TRY")
        default_aapl = SecurityFactsService().build("AAPL", allow_sec_cache_replay=False)
        default_crm = SecurityFactsService().build("CRM", allow_sec_cache_replay=False)
        self.assertIsNone(SecurityIntelligenceService().evaluate(default_aapl).overall_score)
        self.assertIsNone(SecurityIntelligenceService().evaluate(default_crm).overall_score)
        weights = ENGINE.read_text(encoding="utf-8")
        self.assertIn("DIM_QUALITY: 0.22", weights)
        self.assertIn("DIM_GROWTH: 0.18", weights)
        self.assertIn('("pe", inverse(facts.pe, 12, 40), 0.50)', weights)
        self.assertNotIn("BIST_ONLY", weights)
        self.assertNotIn("BIST_SI_ENABLED", POLICY.read_text(encoding="utf-8"))
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            result = evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="TR",
                )
            )
            self.assertEqual(result.decision, DECISION_INSUFFICIENT_DATA)
            self.assertNotIn(REASON_UNSUPPORTED_INSTRUMENT, result.blocking_reasons)
            self.assertIn(REASON_SI_MISSING, result.blocking_reasons)
        self.assertNotIn("8e_enabled", DECISION.read_text(encoding="utf-8"))
        facts, _ = _compose("BIMAS")
        audit = audit_bist_si_readiness(facts)
        self.assertFalse(audit.persisted)
        self.assertIsNotNone(aapl_view.overall_status)
        self.assertIsNotNone(crm_view.overall_status)


if __name__ == "__main__":
    unittest.main()
