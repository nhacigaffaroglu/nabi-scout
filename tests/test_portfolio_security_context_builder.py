from __future__ import annotations

import unittest
from pathlib import Path

from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_intelligence_enrichment_contract import (
    CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT,
)
from services.portfolio_security_context_builder import (
    PortfolioSecuritySourceBundle,
    aggregate_holding,
    build_portfolio_security_context,
    explicit_research_allowed,
    resolve_economic_exposure_status,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.research_workflow_service import DEFAULT_RESEARCH_STATUS
from services.security_intelligence_contract import (
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    STALE_DATA,
    SecurityIntelligenceSnapshot,
    STATE_WATCH,
)
from services.signal_intelligence_contract import (
    DIRECTION_NEGATIVE,
    EVENT_SEC_FILING,
    MATERIALITY_HIGH,
    SecuritySignal,
    SignalIntelligenceContext,
    VERIFIED,
)


BUILDER = Path("services/portfolio_security_context_builder.py")


def _si(
    *,
    state: str = STATE_WATCH,
    score: float = 55.0,
    freshness: str = FRESHNESS_FRESH,
    stale: bool = False,
) -> SecurityIntelligenceSnapshot:
    reasons = (STALE_DATA, "FRESHNESS_STALE") if stale else ()
    return SecurityIntelligenceSnapshot(
        symbol="CRM",
        as_of="2026-08-01",
        engine_version="security_intelligence_8b.1",
        facts_version="security_facts_8c.1",
        overall_score=score,
        overall_status="NEUTRAL",
        investment_state=state,
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        overall_confidence=0.7,
        reason_codes=reasons,
        risk_flags=(STALE_DATA,) if stale else (),
        data_quality={"freshness_status": freshness, "reason_codes": list(reasons)},
    )


def _signal(*, negative: bool = False, conflict: bool = False) -> SignalIntelligenceContext:
    material = ()
    if negative:
        material = (
            SecuritySignal(
                event_id="e1",
                symbol="CRM",
                event_type=EVENT_SEC_FILING,
                event_subtype=None,
                headline="8-K",
                event_time="2026-08-01",
                source_authority="SEC",
                verification_status=VERIFIED,
                materiality=MATERIALITY_HIGH,
                direction=DIRECTION_NEGATIVE,
                strength="STRONG",
                reason_codes=(),
                why_it_matters="",
                evidence_count=1,
            ),
        )
    flags = ("SIGNAL_CONFLICT",) if conflict else (("MATERIAL_NEGATIVE_SIGNAL",) if negative else ())
    return SignalIntelligenceContext(
        symbol="CRM",
        material_signals=material,
        signal_risk_flags=flags,
        latest_material_event_id="e1" if negative else None,
        latest_material_event_at="2026-08-01" if negative else None,
    )


class ExplicitResearchAllowedTests(unittest.TestCase):
    def test_does_not_infer_from_uygun(self) -> None:
        self.assertIsNone(
            explicit_research_allowed(
                snapshot={"status": PARTICIPATION_STATUS_UYGUN},
            )
        )

    def test_reads_queue_boolean_only(self) -> None:
        self.assertTrue(explicit_research_allowed(queue_row={"research_allowed": True}))
        self.assertFalse(explicit_research_allowed(queue_row={"research_allowed": False}))
        self.assertIsNone(explicit_research_allowed(queue_row={"status": "COMPLETED"}))


class PortfolioSecurityContextBuilderTests(unittest.TestCase):
    def test_persisted_si_is_copied_not_reevaluated(self) -> None:
        ctx = build_portfolio_security_context(
            "crm",
            PortfolioSecuritySourceBundle(
                snapshot={"status": PARTICIPATION_STATUS_UYGUN},
                queue_row={"research_allowed": True},
                si_snapshot=_si(state=STATE_WATCH, score=61.0),
                instrument_type="EQUITY",
                market="US",
                economic_exposure_status="STRICT",
            ),
        )
        self.assertEqual(ctx.si_state, STATE_WATCH)
        self.assertEqual(ctx.si_score, 61.0)
        self.assertEqual(ctx.si_as_of, "2026-08-01")
        self.assertEqual(ctx.si_data_quality, "FRESH")
        source = BUILDER.read_text(encoding="utf-8")
        self.assertNotIn("get_investment_intelligence", source)
        self.assertNotIn("evaluate_security_intelligence", source)
        self.assertNotIn("allow_sec_cache_replay", source)

    def test_missing_si_and_research_allowed_stay_missing(self) -> None:
        ctx = build_portfolio_security_context("AAPL", PortfolioSecuritySourceBundle())
        self.assertIsNone(ctx.si_state)
        self.assertIsNone(ctx.research_allowed)
        self.assertIsNone(ctx.participation_status)
        self.assertIn("si_state", ctx.missing_inputs)
        self.assertIn("research_allowed", ctx.missing_inputs)
        result = evaluate_portfolio_security_decision(ctx)
        self.assertFalse(result.exposure_increase_allowed)

    def test_signal_context_maps_verified_material_negative(self) -> None:
        ctx = build_portfolio_security_context(
            "CRM",
            PortfolioSecuritySourceBundle(
                snapshot={"status": PARTICIPATION_STATUS_UYGUN},
                queue_row={"research_allowed": True},
                si_snapshot=_si(),
                signal_context=_signal(negative=True),
            ),
        )
        self.assertTrue(ctx.verified_material_negative)
        self.assertFalse(ctx.verified_material_positive)
        self.assertEqual(ctx.latest_material_signal, "e1")

    def test_signal_conflict_flag(self) -> None:
        ctx = build_portfolio_security_context(
            "CRM",
            PortfolioSecuritySourceBundle(signal_context=_signal(conflict=True)),
        )
        self.assertTrue(ctx.signal_conflict)

    def test_portfolio_holding_aggregation_from_objects(self) -> None:
        class _Row:
            def __init__(self) -> None:
                self.symbol = "AAPL"
                self.quantity = 30.0
                self.market_value = 9280.5
                self.weight_pct = 10.6
                self.market = "US"

        qty, value, weight, market = aggregate_holding([_Row()], "AAPL")
        self.assertEqual(qty, 30.0)
        self.assertEqual(value, 9280.5)
        self.assertEqual(weight, 10.6)
        self.assertEqual(market, "US")

    def test_portfolio_holding_aggregation(self) -> None:
        qty, value, weight, _market = aggregate_holding(
            [
                {"symbol": "CRM", "quantity": 4, "market_value": 1000, "weight_pct": 6.0},
                {"symbol": "CRM", "quantity": 1, "market_value": 250, "weight_pct": 1.5},
            ],
            "CRM",
        )
        ctx = build_portfolio_security_context(
            "CRM",
            PortfolioSecuritySourceBundle(
                quantity=qty,
                market_value=value,
                portfolio_weight=weight,
                market="US",
                instrument_type="EQUITY",
            ),
        )
        self.assertTrue(ctx.is_holding)
        self.assertEqual(ctx.quantity, 5)
        self.assertEqual(ctx.market_value, 1250)
        self.assertEqual(ctx.portfolio_weight, 7.5)
        self.assertEqual(ctx.concentration_ceiling, CONCENTRATION_SINGLE_POSITION_THRESHOLD_PCT)

    def test_yeni_lifecycle_preserved(self) -> None:
        ctx = build_portfolio_security_context(
            "ADBE",
            PortfolioSecuritySourceBundle(
                snapshot={"status": PARTICIPATION_STATUS_UYGUN},
                queue_row={"research_allowed": True},
                si_snapshot=None,
                candidate={"symbol": "ADBE", "research_status": DEFAULT_RESEARCH_STATUS},
                instrument_type="EQUITY",
                market="US",
            ),
        )
        self.assertTrue(ctx.candidate_exists)
        self.assertEqual(ctx.research_status, "YENI")
        result = evaluate_portfolio_security_decision(ctx)
        self.assertEqual(result.research_status, "YENI")
        self.assertFalse(result.exposure_increase_allowed)

    def test_uygun_does_not_set_research_allowed(self) -> None:
        ctx = build_portfolio_security_context(
            "CRM",
            PortfolioSecuritySourceBundle(snapshot={"status": PARTICIPATION_STATUS_UYGUN}),
        )
        self.assertEqual(ctx.participation_status, PARTICIPATION_STATUS_UYGUN)
        self.assertIsNone(ctx.research_allowed)

    def test_economic_status_uses_existing_hybrid_resolver(self) -> None:
        self.assertEqual(resolve_economic_exposure_status(), "STRICT")

    def test_builder_propagates_canonical_stale_si(self) -> None:
        stale = build_portfolio_security_context(
            "CRM",
            PortfolioSecuritySourceBundle(
                snapshot={"status": PARTICIPATION_STATUS_UYGUN},
                queue_row={"research_allowed": True},
                si_snapshot=_si(stale=True, freshness=FRESHNESS_STALE),
            ),
        )
        fresh = build_portfolio_security_context(
            "CRM",
            PortfolioSecuritySourceBundle(si_snapshot=_si()),
        )
        unknown = build_portfolio_security_context(
            "CRM",
            PortfolioSecuritySourceBundle(
                si_snapshot=_si(freshness=FRESHNESS_UNKNOWN)
            ),
        )
        missing = build_portfolio_security_context("TSLA", PortfolioSecuritySourceBundle())
        self.assertEqual(stale.stale_inputs, ("si",))
        self.assertEqual(fresh.stale_inputs, ())
        self.assertEqual(unknown.stale_inputs, ())
        self.assertEqual(missing.stale_inputs, ())
        self.assertIsNone(missing.si_state)
        source = BUILDER.read_text(encoding="utf-8")
        self.assertNotIn("get_investment_intelligence", source)
        self.assertNotIn("evaluate_security_intelligence", source)
        self.assertIn("persisted_snapshot_is_stale", source)


if __name__ == "__main__":
    unittest.main()
