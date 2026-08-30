from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from services.bist_si_readiness import EVAL_SAFE
from services.hybrid_exposure_allocation_policy import HybridPortfolioMode
from services.kap_eps_normalization import BASIS_UNRESOLVED, asels_anomaly_classification
from services.nabi_adviser_context import resolve_adviser_security_decisions
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_allocation_intelligence import _map_market
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.portfolio_security_decision_contract import (
    DECISION_CONSIDER_TOP_UP,
    DECISION_HOLD,
    DECISION_REVIEW,
    DECISION_WATCH,
    PortfolioSecurityContext,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_SI_MISSING,
    REASON_SI_STALE,
    REASON_UNSUPPORTED_INSTRUMENT,
)
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.portfolio_security_decision_service import evaluate_portfolio_security_for_symbol
from services.security_intelligence_contract import (
    FRESHNESS_STALE,
    PERIOD_YTD,
    STATE_ATTRACTIVE,
    SecurityFacts,
    SecurityParticipationContext,
    persisted_snapshot_is_stale,
)
from services.security_intelligence_publish import (
    REASON_IDENTITY_MISSING,
    REASON_INSUFFICIENT_FACTS,
    REASON_UNSAFE_PERIOD,
    publish_canonical_security_intelligence,
)
from services.security_intelligence_snapshot_service import (
    latest_snapshot,
    save_security_intelligence_snapshot,
)
from services.security_master_contract import INSTRUMENT_EQUITY, INSTRUMENT_ETF
from services.security_master_service import SecurityMasterService
from repositories.security_intelligence_snapshot_repository import (
    SecurityIntelligenceSnapshotRepository,
)
from tests.test_bist_si_production_gate import _compose
from tests.test_security_intelligence_snapshots import _FakeRepo


ENGINE = Path("services/security_intelligence_publish.py")
SNAPSHOT = Path("services/security_intelligence_snapshot_service.py")
REPO = Path("repositories/security_intelligence_snapshot_repository.py")
HOLDINGS = {
    "ASELS": (680.0, 5701.57, 6.52),
    "BIMAS": (1594.0, 13812.88, 15.79),
    "TUPRS": (1032.0, 8491.94, 9.71),
}
class _Table:
    def __init__(self, store: Dict[str, List[Dict[str, Any]]], name: str) -> None:
        self._store = store
        self._name = name
        self._rows = list(store.get(name, []))
        self._filters: List[tuple[str, Any]] = []
        self._desc = False
        self._order_key: Optional[str] = None
        self._limit: Optional[int] = None
        self._range: Optional[tuple[int, int]] = None

    def select(self, *_args: Any, **_kwargs: Any) -> "_Table":
        return self

    def eq(self, key: str, value: Any) -> "_Table":
        self._filters.append((key, value))
        return self

    def order(self, key: str, desc: bool = False, **_kwargs: Any) -> "_Table":
        self._order_key = key
        self._desc = desc
        return self

    def limit(self, count: int) -> "_Table":
        self._limit = count
        return self

    def range(self, start: int, end: int) -> "_Table":
        self._range = (start, end)
        return self

    def upsert(self, payload: Dict[str, Any], on_conflict: str = "") -> "_Table":
        rows = self._store.setdefault(self._name, [])
        keys = [part.strip() for part in str(on_conflict or "").split(",") if part.strip()]
        stored = dict(payload)
        if keys:
            ident = tuple(str(stored.get(key) or "") for key in keys)
            for index, row in enumerate(rows):
                if tuple(str(row.get(key) or "") for key in keys) == ident:
                    rows[index] = stored
                    self._rows = [stored]
                    return self
        rows.append(stored)
        self._rows = [stored]
        return self

    def insert(self, payload: Dict[str, Any]) -> "_Table":
        raise RuntimeError(f"blocked write on {self._name}.insert")

    def update(self, *_args: Any, **_kwargs: Any) -> "_Table":
        raise RuntimeError(f"blocked write on {self._name}.update")

    def delete(self, *_args: Any, **_kwargs: Any) -> "_Table":
        raise RuntimeError(f"blocked write on {self._name}.delete")

    def execute(self) -> SimpleNamespace:
        rows = list(self._store.get(self._name, self._rows))
        for key, value in self._filters:
            rows = [
                row
                for row in rows
                if str(row.get(key) or "").strip().upper() == str(value or "").strip().upper()
            ]
        if self._order_key:
            rows.sort(key=lambda row: str(row.get(self._order_key) or ""), reverse=self._desc)
        if self._range is not None:
            start, end = self._range
            rows = rows[start : end + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return SimpleNamespace(data=rows)


class _MemoryClient:
    def __init__(self) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "security_intelligence_snapshots": [],
            "participation_assessment_snapshots": [],
            "universe_expansion_queue": [],
            "investment_candidates": [],
            "security_master": [],
        }

    def table(self, name: str) -> _Table:
        self.tables.setdefault(name, [])
        return _Table(self.tables, name)


def _participation(status: str = PARTICIPATION_STATUS_UYGUN) -> SecurityParticipationContext:
    return SecurityParticipationContext(status=status, research_allowed=True)


def _publish(facts, repo, *, participation=None, identity_ok=True, kap_bundle=None, dry_run=False):
    return publish_canonical_security_intelligence(
        facts,
        participation or _participation(),
        repo,
        identity_ok=identity_ok,
        kap_bundle=kap_bundle,
        dry_run=dry_run,
    )


def _position(symbol: str) -> PositionValuationRow:
    qty, market_value, weight = HOLDINGS[symbol]
    return PositionValuationRow(
        position_id=f"p-{symbol}",
        account_id="acc-1",
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class="equity",
        account_name="Broker",
        quantity=qty,
        average_cost=100.0,
        valuation_currency="USD",
        price=market_value / qty,
        price_available=True,
        market_value=market_value,
        cost_basis=market_value,
        unrealized_pl=0.0,
        weight_pct=weight,
        is_cash=False,
        included_in_base_totals=True,
    )


def _portfolio_view() -> PortfolioIntelligenceView:
    priced = [_position(symbol) for symbol in HOLDINGS]
    return PortfolioIntelligenceView(
        portfolio_id="a991d5f6-becc-4c37-b4f5-6421239aea07",
        portfolio_name="Ana Portföy",
        base_currency="USD",
        priced_total_market_value=sum(float(row.market_value or 0) for row in priced),
        priced_total_cost_basis=1.0,
        priced_total_unrealized_pl=0.0,
        priced_position_count=3,
        unpriced_position_count=0,
        foreign_currency_position_count=0,
        total_position_count=3,
        mixed_currency_warning=False,
        fx_supported=True,
        priced_positions=priced,
        unpriced_positions=[],
        foreign_currency_positions=[],
        asset_class_allocation=[AllocationSlice("equity", "equity", 1.0, 100.0)],
        account_allocation=[AllocationSlice("acc-1", "Broker", 1.0, 100.0)],
        health=PortfolioHealthMetrics(15.79, 39.68, 100.0, 0.0, 100.0, 100.0),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


def _seed_participation(client: _MemoryClient, symbol: str, status: str) -> None:
    client.tables["participation_assessment_snapshots"].append(
        {
            "symbol": symbol,
            "participation_status": status,
            "status": status,
            "research_allowed": True,
            "assessed_at": "2026-08-28T00:00:00+00:00",
        }
    )


def _runtime_8e(client: _MemoryClient, symbol: str):
    with patch(
        "services.portfolio_security_decision_service._portfolio_view",
        return_value=_portfolio_view(),
    ), patch(
        "services.portfolio_security_decision_service._lookthrough_symbols",
        return_value=set(),
    ):
        return evaluate_portfolio_security_for_symbol(client, symbol, user_id="user-1")


class CanonicalPublishContractTests(unittest.TestCase):
    def test_same_repository_and_no_manual_scores(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("save_security_intelligence_snapshot", source)
        self.assertIn("SecurityIntelligenceService", source)
        self.assertNotIn("53.6", source)
        self.assertNotIn("43.7", source)
        self.assertNotIn("29.7", source)
        self.assertNotIn("BIST_SI_STORE", source)
        self.assertNotIn("if symbol in", source)
        self.assertEqual(
            SecurityIntelligenceSnapshotRepository.TABLE,
            "security_intelligence_snapshots",
        )
        self.assertIn("security_intelligence_snapshots", REPO.read_text(encoding="utf-8"))
        self.assertNotIn("allocate_new_money", source)
        self.assertNotIn("245", source)

    def test_compose_evaluate_persist_for_pilots(self) -> None:
        repo = _FakeRepo()
        published = {}
        for symbol in ("ASELS", "BIMAS", "TUPRS"):
            facts, history = _compose(symbol)
            result = _publish(facts, repo, kap_bundle=history.latest().bundle)
            self.assertTrue(result.published, symbol)
            self.assertIsNotNone(result.view)
            self.assertIsNotNone(result.view.overall_score)
            self.assertTrue(result.eligibility.production_quality_sufficient)
            self.assertEqual(result.eligibility.shadow_evaluation, EVAL_SAFE)
            snap = latest_snapshot(repo, symbol)
            self.assertIsNotNone(snap)
            self.assertEqual(snap.symbol, symbol)
            self.assertEqual(snap.investment_state, result.view.investment_state)
            published[symbol] = result
        self.assertEqual(asels_anomaly_classification(656.79), BASIS_UNRESOLVED)
        self.assertIsNone(_compose("ASELS")[0].pe)
        self.assertTrue(published["ASELS"].published)

    def test_idempotency_and_history(self) -> None:
        facts, history = _compose("BIMAS")
        repo = _FakeRepo()
        first = _publish(facts, repo, kap_bundle=history.latest().bundle)
        second = _publish(facts, repo, kap_bundle=history.latest().bundle)
        self.assertTrue(first.published)
        self.assertTrue(second.skipped_duplicate)
        self.assertEqual(repo.upserts, 1)
        later = replace(facts, as_of="2026-08-29")
        third = _publish(later, repo, kap_bundle=history.latest().bundle)
        self.assertTrue(third.published)
        self.assertEqual(len(repo.rows), 2)
        latest = latest_snapshot(repo, "BIMAS")
        self.assertEqual(latest.as_of, "2026-08-29")

    def test_asels_missing_eps_allowed_under_canonical_rules(self) -> None:
        facts, history = _compose("ASELS")
        self.assertIsNone(facts.eps)
        self.assertIsNone(facts.pe)
        self.assertEqual(asels_anomaly_classification(656.79), BASIS_UNRESOLVED)
        result = _publish(facts, _FakeRepo(), kap_bundle=history.latest().bundle)
        self.assertTrue(result.published)
        self.assertTrue(result.eligibility.can_score)
        self.assertTrue(result.eligibility.production_quality_sufficient)


class FailureMatrixTests(unittest.TestCase):
    def test_missing_and_insufficient_facts(self) -> None:
        empty = SecurityFacts(symbol="EQBISTX", currency="TRY", exchange="BIST", instrument_type=INSTRUMENT_EQUITY)
        missing = _publish(empty, _FakeRepo())
        self.assertFalse(missing.published)
        self.assertTrue(missing.blocked)
        self.assertIn(missing.block_reason, {REASON_INSUFFICIENT_FACTS, REASON_UNSAFE_PERIOD})
        facts, history = _compose("TUPRS")
        ytd = replace(facts, period_kind=PERIOD_YTD)
        unsafe = _publish(ytd, _FakeRepo(), kap_bundle=history.latest().bundle)
        self.assertFalse(unsafe.published)
        self.assertEqual(unsafe.block_reason, REASON_UNSAFE_PERIOD)

    def test_missing_identity_and_unsupported_instrument(self) -> None:
        facts, history = _compose("ASELS")
        blocked = _publish(facts, _FakeRepo(), identity_ok=False, kap_bundle=history.latest().bundle)
        self.assertFalse(blocked.published)
        self.assertEqual(blocked.block_reason, REASON_IDENTITY_MISSING)
        etf = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="SPUS",
                participation_status=PARTICIPATION_STATUS_UYGUN,
                research_allowed=True,
                si_state=STATE_ATTRACTIVE,
                instrument_type=INSTRUMENT_ETF,
                market="US",
                economic_exposure_status=HybridPortfolioMode.STRICT.value,
            )
        )
        self.assertIn(REASON_UNSUPPORTED_INSTRUMENT, etf.blocking_reasons)

    def test_missing_momentum_and_unresolved_ca_do_not_increase(self) -> None:
        facts, history = _compose("TUPRS", with_momentum=False)
        result = _publish(facts, _FakeRepo(), kap_bundle=history.latest().bundle)
        self.assertTrue(result.published or result.blocked)
        if result.view is not None:
            self.assertNotIn(result.view.investment_state, ("ATTRACTIVE",))

    def test_stale_snapshot_fail_closed(self) -> None:
        facts, history = _compose("ASELS")
        repo = _FakeRepo()
        published = _publish(facts, repo, kap_bundle=history.latest().bundle)
        self.assertTrue(published.published)
        row = repo.get_latest("ASELS")
        quality = dict(row.get("data_quality") or {})
        quality["freshness_status"] = FRESHNESS_STALE
        row["data_quality"] = quality
        snap = latest_snapshot(repo, "ASELS")
        self.assertTrue(persisted_snapshot_is_stale(snap))
        stale = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="ASELS",
                participation_status=PARTICIPATION_STATUS_UYGUN,
                research_allowed=True,
                si_state=snap.investment_state,
                si_score=snap.overall_score,
                is_holding=True,
                quantity=680,
                market_value=5701.57,
                portfolio_weight=6.52,
                economic_exposure_status=HybridPortfolioMode.STRICT.value,
                instrument_type=INSTRUMENT_EQUITY,
                market="TR",
                stale_inputs=("si",),
            )
        )
        self.assertFalse(stale.exposure_increase_allowed)
        self.assertEqual(stale.decision, DECISION_REVIEW)
        self.assertIn(REASON_SI_STALE, stale.blocking_reasons)

    def test_newer_facts_create_history_not_overwrite(self) -> None:
        facts, history = _compose("BIMAS")
        repo = _FakeRepo()
        first = _publish(facts, repo, kap_bundle=history.latest().bundle)
        newer = replace(facts, as_of="2026-08-30", facts_version=f"{facts.facts_version}-next")
        second = _publish(newer, repo, kap_bundle=history.latest().bundle)
        self.assertTrue(first.published)
        self.assertTrue(second.published)
        self.assertEqual(len(repo.rows), 2)
        self.assertEqual(latest_snapshot(repo, "BIMAS").as_of, "2026-08-30")


class RuntimeEightETests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _MemoryClient()
        self.repo = SecurityIntelligenceSnapshotRepository(self.client)
        for symbol in HOLDINGS:
            facts, history = _compose(symbol)
            result = _publish(facts, self.repo, kap_bundle=history.latest().bundle)
            self.assertTrue(result.published, symbol)
            _seed_participation(self.client, symbol, PARTICIPATION_STATUS_UYGUN)
            setattr(self, f"_{symbol.lower()}_view", result.view)

    def test_production_8e_and_adviser_no_si_missing(self) -> None:
        decisions = {}
        for symbol in HOLDINGS:
            result = _runtime_8e(self.client, symbol)
            self.assertNotIn(REASON_SI_MISSING, result.blocking_reasons, symbol)
            self.assertIsNotNone(result.security_intelligence_state)
            self.assertFalse(result.exposure_increase_allowed)
            decisions[symbol] = result
        with patch(
            "services.portfolio_security_decision_service._portfolio_view",
            return_value=_portfolio_view(),
        ), patch(
            "services.portfolio_security_decision_service._lookthrough_symbols",
            return_value=set(),
        ):
            resolved = resolve_adviser_security_decisions(
                HOLDINGS.keys(),
                client=self.client,
                user_id="user-1",
            )
        by_symbol = {item.symbol: item for item in resolved}
        for symbol in HOLDINGS:
            self.assertNotIn(REASON_SI_MISSING, by_symbol[symbol].blocking_reasons)
            self.assertFalse(by_symbol[symbol].exposure_increase_allowed)
        expected = {
            "WATCH": DECISION_WATCH,
            "NEUTRAL": DECISION_WATCH,
            "CAUTION": DECISION_REVIEW,
            "AVOID": DECISION_HOLD,
        }
        for symbol, result in decisions.items():
            state = result.security_intelligence_state
            self.assertEqual(result.decision, expected[state], symbol)
            self.assertFalse(result.exposure_increase_allowed)

    def test_participation_change_after_stored_si(self) -> None:
        self.client.tables["participation_assessment_snapshots"] = [
            {
                "symbol": "ASELS",
                "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                "status": PARTICIPATION_STATUS_KONTROL_ET,
                "research_allowed": True,
                "assessed_at": "2026-08-29T00:00:00+00:00",
            }
        ]
        kontrol = _runtime_8e(self.client, "ASELS")
        self.assertEqual(kontrol.decision, DECISION_REVIEW)
        self.assertFalse(kontrol.exposure_increase_allowed)
        self.assertIn(REASON_PARTICIPATION_NOT_UYGUN, kontrol.blocking_reasons)
        self.client.tables["participation_assessment_snapshots"] = [
            {
                "symbol": "ASELS",
                "participation_status": PARTICIPATION_STATUS_UYGUN_DEGIL,
                "status": PARTICIPATION_STATUS_UYGUN_DEGIL,
                "research_allowed": True,
                "assessed_at": "2026-08-29T00:00:00+00:00",
            }
        ]
        blocked = _runtime_8e(self.client, "ASELS")
        self.assertEqual(blocked.decision, DECISION_HOLD)
        self.assertFalse(blocked.exposure_increase_allowed)
        self.assertIn(REASON_PARTICIPATION_NOT_UYGUN, blocked.blocking_reasons)

    def test_no_new_money_or_portfolio_mutation(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("post_transaction", source)
        self.assertNotIn("allocate_new_money", source)
        with self.assertRaises(RuntimeError):
            self.client.table("wealth_positions").insert({"symbol": "ASELS"}).execute()


class UsParityAndMarketAliasTests(unittest.TestCase):
    def test_aapl_crm_engine_parity(self) -> None:
        def _us(symbol: str):
            return evaluate_portfolio_security_decision(
                PortfolioSecurityContext(
                    symbol=symbol,
                    participation_status=PARTICIPATION_STATUS_UYGUN,
                    research_allowed=True,
                    si_state=STATE_ATTRACTIVE,
                    si_score=72.0,
                    is_holding=True,
                    quantity=10.0,
                    market_value=2500.0,
                    portfolio_weight=5.0,
                    economic_exposure_status=HybridPortfolioMode.STRICT.value,
                    instrument_type=INSTRUMENT_EQUITY,
                    market="US",
                )
            )

        aapl = _us("AAPL")
        crm = _us("CRM")
        self.assertEqual(aapl.decision, DECISION_CONSIDER_TOP_UP)
        self.assertEqual(crm.decision, DECISION_CONSIDER_TOP_UP)
        self.assertTrue(aapl.exposure_increase_allowed)
        self.assertTrue(crm.exposure_increase_allowed)

    def test_us_facts_use_same_snapshot_contract(self) -> None:
        facts = SecurityFacts(
            symbol="AAPL",
            currency="USD",
            exchange="NASDAQ",
            instrument_type=INSTRUMENT_EQUITY,
            revenue=390_000,
            roic=40,
            pe=30,
            as_of="2026-08-28",
        )
        view = __import__(
            "services.security_intelligence_service",
            fromlist=["SecurityIntelligenceService"],
        ).SecurityIntelligenceService().evaluate(facts, _participation())
        repo = _FakeRepo()
        save = save_security_intelligence_snapshot(repo, view, as_of=facts.as_of)
        self.assertTrue(save.saved or view.overall_score is not None)
        self.assertEqual(SecurityIntelligenceSnapshotRepository.TABLE, "security_intelligence_snapshots")

    def test_market_alias_issue_reported_not_changed(self) -> None:
        self.assertEqual(_map_market("US"), "us")
        self.assertEqual(_map_market("NASDAQ"), "other")
        self.assertEqual(_map_market("TR"), "tr")
        self.assertEqual(_map_market("BIST"), "tr")
        self.assertEqual(_map_market("IST"), "other")
        self.assertEqual(_map_market("XIST"), "other")

    def test_security_master_still_resolves_bist_equity(self) -> None:
        master = SecurityMasterService()
        for symbol in HOLDINGS:
            resolution = master.resolve_security(symbol)
            self.assertEqual(resolution.instrument_type, INSTRUMENT_EQUITY)


if __name__ == "__main__":
    unittest.main()
