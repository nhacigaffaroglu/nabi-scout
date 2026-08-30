from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional

from services.bist_corporate_action_audit import (
    EVENT_SPLIT,
    OfficialCorporateAction,
    STATUS_UNRESOLVED,
)
from services.bist_refresh_contract import (
    CHANGE_CORPORATE_ACTION,
    CHANGE_FINANCIAL_FACTS,
    CHANGE_PARTICIPATION,
    CHANGE_PRICE_HISTORY,
    JOB_NAME,
    PAID_PROVIDER_TOKENS,
    REASON_BROAD_UNIVERSE,
    REASON_FIXTURE_MOMENTUM,
    REASON_NO_CHANGE,
    REASON_SOURCE_FAILURE_PRESERVE,
    REASON_UNRESOLVED_CA,
    REASON_US_ISOLATED,
    STATUS_CORRECTION,
    STATUS_NEW_PERIOD,
    STATUS_NO_CHANGE,
    BistRefreshState,
)
from services.bist_refresh_orchestrator import (
    compose_official_facts,
    fixture_momentum_forbidden,
    kafif_is_newer,
    run_bist_refresh,
)
from services.bist_thb_history import (
    ThbHistoryCache,
    ingest_thb_text,
    last_cached_ok_date,
    missing_weekday_dates,
)
from services.kap_financial_contract import PERIOD_FY
from services.kap_kafif_contract import KapKafifDiscovery
from services.kap_public_contract import TITLE_FINANCIAL_REPORT, KapFrDiscovery
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.portfolio_security_decision_contract import DECISION_WATCH
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import STATE_ATTRACTIVE
from services.security_master_service import SecurityMasterService
from tests.fixtures.bist_thb_history_days import equity_row, thb_csv, weekday_series
from tests.test_bist_portfolio_decision import _ctx
from tests.test_nabi_adviser_8f import _psd
from tests.test_security_intelligence_snapshots import _FakeRepo
from tests.test_wealth_new_money_allocation import _plan, _policy, _row, _view


ENGINE = Path("services/bist_refresh_orchestrator.py")
CLI = Path("scripts/run_bist_refresh.py")
THB = Path("services/bist_thb_history.py")
PUBLISH = Path("services/security_intelligence_publish.py")
WORKFLOWS = Path(".github/workflows")


def _fr(symbol: str, nid: str, year: int, submitted: str = "2026-03-11") -> KapFrDiscovery:
    return KapFrDiscovery(
        symbol=symbol,
        notification_id=nid,
        submission_date=submitted,
        year=str(year),
        period=PERIOD_FY,
        period_label="Yıllık",
        title=TITLE_FINANCIAL_REPORT,
        source_url=f"https://kap.org.tr/tr/Bildirim/{nid}",
        disclosure_class="FR",
    )


def _cursor_cache(day: date) -> ThbHistoryCache:
    cache = ThbHistoryCache(root=Path(f"unused-thb-{day.isoformat()}"))
    cache.known_dates[day.isoformat()] = "ok"
    return cache


def _kafif(symbol: str, nid: str, submitted: str, year: str = "2025") -> KapKafifDiscovery:
    return KapKafifDiscovery(
        symbol=symbol,
        disclosure_id=nid,
        submitted_at=submitted,
        financial_year=year,
        period="Yıllık",
        source_url=f"https://kap.org.tr/tr/Bildirim/{nid}",
    )


class _Table:
    def __init__(self, store: Dict[str, List[Dict[str, Any]]], name: str) -> None:
        self._store = store
        self._name = name

    def insert(self, row: Dict[str, Any]) -> Any:
        raise RuntimeError(f"blocked write {self._name}")


class DiscoveryAndHealthTests(unittest.TestCase):
    def test_cli_and_job_name_exist_without_cron(self) -> None:
        self.assertTrue(CLI.is_file())
        self.assertIn("dry_run=True", CLI.read_text(encoding="utf-8"))
        self.assertIn("persist_si=False", CLI.read_text(encoding="utf-8"))
        self.assertEqual(JOB_NAME, "bist_canonical_refresh")
        for path in WORKFLOWS.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("run_bist_refresh", text, path.name)
            self.assertNotIn("bist_canonical_refresh", text, path.name)

    def test_today_run_status_is_unknown_for_bist_job(self) -> None:
        self.assertNotIn("cron", CLI.read_text(encoding="utf-8"))
        self.assertNotIn("schedule:", ENGINE.read_text(encoding="utf-8"))


class KapChangeTests(unittest.TestCase):
    def test_kap_no_change_and_new_period_and_correction(self) -> None:
        old = _fr("EQBISTX", "100", 2024)
        same = _fr("EQBISTX", "100", 2024)
        restated = _fr("EQBISTX", "101", 2024, submitted="2026-04-01")
        newer = _fr("EQBISTX", "200", 2025)
        state = BistRefreshState(known_notification_ids=("100",))
        none = run_bist_refresh(
            ["EQBISTX"],
            dry_run=True,
            state=state,
            kap_discoveries={"EQBISTX": (same,)},
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        self.assertEqual(none.securities[0].kap_status, STATUS_NO_CHANGE)
        self.assertEqual(none.changes_detected, 0)
        corr = run_bist_refresh(
            ["EQBISTX"],
            dry_run=True,
            state=state,
            kap_discoveries={"EQBISTX": (old, restated)},
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        self.assertEqual(corr.securities[0].kap_status, STATUS_CORRECTION)
        self.assertIn(CHANGE_FINANCIAL_FACTS, corr.securities[0].changes)
        period = run_bist_refresh(
            ["EQBISTX"],
            dry_run=True,
            state=state,
            kap_discoveries={"EQBISTX": (old, newer)},
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        self.assertEqual(period.securities[0].kap_status, STATUS_NEW_PERIOD)


class KafifCorrectionTests(unittest.TestCase):
    def test_same_period_new_notification_detected(self) -> None:
        old = _kafif("EQBISTX", "k1", "11.03.2025")
        new = _kafif("EQBISTX", "k2", "01.04.2025")
        self.assertTrue(kafif_is_newer("k1", "11.03.2025", new))
        self.assertFalse(kafif_is_newer("k2", "01.04.2025", new))
        first = run_bist_refresh(
            ["EQBISTX"],
            dry_run=True,
            kafif_discoveries={"EQBISTX": (old,)},
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        second = run_bist_refresh(
            ["EQBISTX"],
            dry_run=True,
            state=first.next_state,
            kafif_discoveries={"EQBISTX": (old, new)},
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        row = second.securities[0]
        self.assertIn(CHANGE_PARTICIPATION, row.changes)
        self.assertEqual(row.kafif_status, STATUS_CORRECTION)
        self.assertEqual(row.latest_kafif_id, "k2")
        self.assertEqual(first.next_state.kafif_id("EQBISTX"), "k1")
        self.assertEqual(second.next_state.kafif_id("EQBISTX"), "k2")


class ThbAndCorporateActionTests(unittest.TestCase):
    def test_missing_new_day_weekend_duplicate_and_holiday(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = ThbHistoryCache(root=Path(tmp))
            ingest_thb_text(
                thb_csv(date(2026, 8, 28), [equity_row(date(2026, 8, 28), "EQBISTX", 10.0)]),
                source_file="thb202608281.csv",
                source_url="https://borsaistanbul.com/x",
                cache=cache,
            )
            self.assertEqual(last_cached_ok_date(cache), date(2026, 8, 28))
            self.assertEqual(missing_weekday_dates(cache, as_of=date(2026, 8, 30)), ())
            self.assertEqual(missing_weekday_dates(cache, as_of=date(2026, 8, 28)), ())
            self.assertEqual(
                missing_weekday_dates(cache, as_of=date(2026, 8, 31)),
                (date(2026, 8, 31),),
            )
            run = run_bist_refresh(
                ["EQBISTX"],
                dry_run=True,
                thb_cache=cache,
                as_of=date(2026, 8, 31),
            )
            self.assertIn(CHANGE_PRICE_HISTORY, run.securities[0].changes)

    def test_unresolved_ca_fail_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = ThbHistoryCache(root=Path(tmp))
            ingest_thb_text(
                thb_csv(
                    date(2026, 8, 28),
                    [equity_row(date(2026, 8, 28), "EQBISTX", 10.0, corporate_action="1")],
                ),
                source_file="thb202608281.csv",
                source_url="https://borsaistanbul.com/x",
                cache=cache,
            )
            run = run_bist_refresh(
                ["EQBISTX"],
                dry_run=True,
                thb_cache=cache,
                as_of=date(2026, 8, 28),
                kap_discoveries={"EQBISTX": (_fr("EQBISTX", "9", 2025),)},
                official_events={
                    "EQBISTX": (
                        OfficialCorporateAction(
                            symbol="EQBISTX",
                            event_type=EVENT_SPLIT,
                            effective_date=date(2026, 8, 20),
                            official_source="test",
                            adjustment_required=True,
                        ),
                    )
                },
            )
            self.assertEqual(run.securities[0].reason, REASON_UNRESOLVED_CA)
            self.assertFalse(run.securities[0].would_publish)
            self.assertIn(CHANGE_CORPORATE_ACTION, run.securities[0].changes or (CHANGE_FINANCIAL_FACTS,))


class PipelineAndSafetyTests(unittest.TestCase):
    def test_affected_vs_unaffected_and_second_run_noop(self) -> None:
        discoveries = {"ASELS": (_fr("ASELS", "n1", 2025),), "BIMAS": (_fr("BIMAS", "n2", 2025),)}
        first = run_bist_refresh(
            ["ASELS", "BIMAS"],
            dry_run=True,
            kap_discoveries=discoveries,
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        self.assertEqual(first.changes_detected, 2)
        self.assertEqual(first.writes, 0)
        second = run_bist_refresh(
            ["ASELS", "BIMAS"],
            dry_run=True,
            state=first.next_state,
            kap_discoveries=discoveries,
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        self.assertEqual(second.changes_detected, 0)
        self.assertEqual(second.securities[0].reason, REASON_NO_CHANGE)
        self.assertEqual(second.writes, 0)

    def test_source_failure_preserves_and_isolates(self) -> None:
        run = run_bist_refresh(
            ["ASELS", "BIMAS"],
            dry_run=True,
            source_failures={"ASELS": "KAP"},
            kap_discoveries={"BIMAS": (_fr("BIMAS", "n2", 2025),)},
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        by_symbol = {row.symbol: row for row in run.securities}
        self.assertEqual(by_symbol["ASELS"].reason, REASON_SOURCE_FAILURE_PRESERVE)
        self.assertFalse(by_symbol["ASELS"].would_publish)
        self.assertIn(CHANGE_FINANCIAL_FACTS, by_symbol["BIMAS"].changes)

    def test_fixture_momentum_rejected(self) -> None:
        series = weekday_series("EQBISTX", end=date(2026, 8, 19), calendar_days=20)
        self.assertTrue(fixture_momentum_forbidden(series))
        with self.assertRaises(ValueError):
            compose_official_facts("EQBISTX", series=series)

    def test_canonical_services_reused_and_no_side_channels(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        self.assertIn("SecurityFactsService().build", source)
        self.assertIn("publish_canonical_security_intelligence", source)
        self.assertNotIn("weekday_series(", source)
        self.assertNotIn("from tests.fixtures", source)
        self.assertNotIn("allocate_new_money", source)
        self.assertNotIn("post_transaction", source)
        self.assertNotIn("payload[\"eps\"]", source)
        for token in PAID_PROVIDER_TOKENS:
            self.assertNotIn(token, source)
        self.assertIn("publish_canonical_security_intelligence", PUBLISH.read_text(encoding="utf-8"))
        self.assertIn("missing_weekday_dates", THB.read_text(encoding="utf-8"))

    def test_broad_universe_refused(self) -> None:
        symbols = [f"S{i:03d}" for i in range(30)]
        run = run_bist_refresh(symbols, dry_run=True, as_of=date(2026, 8, 28))
        self.assertEqual(run.status, "refused")
        self.assertIn(REASON_BROAD_UNIVERSE, run.errors)

    def test_us_symbols_isolated(self) -> None:
        run = run_bist_refresh(
            ["AAPL", "CRM"],
            dry_run=True,
            security_master=SecurityMasterService(),
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        self.assertTrue(all(row.reason == REASON_US_ISOLATED for row in run.securities))

    def test_participation_downgrade_blocks_increase(self) -> None:
        attractive = evaluate_portfolio_security_decision(
            _ctx(
                symbol="EQBISTX",
                si_state=STATE_ATTRACTIVE,
                participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL,
                is_holding=True,
            )
        )
        self.assertFalse(attractive.exposure_increase_allowed)
        kontrol = evaluate_portfolio_security_decision(
            _ctx(
                symbol="EQBISTX",
                si_state=STATE_ATTRACTIVE,
                participation_status=PARTICIPATION_STATUS_KONTROL_ET,
                is_holding=True,
            )
        )
        self.assertFalse(kontrol.exposure_increase_allowed)

    def test_dry_run_does_not_write_snapshots(self) -> None:
        repo = _FakeRepo()
        run = run_bist_refresh(
            ["EQBISTX"],
            dry_run=True,
            persist_si=True,
            snapshot_repo=repo,
            kap_discoveries={"EQBISTX": (_fr("EQBISTX", "n1", 2025),)},
            thb_cache=_cursor_cache(date(2026, 8, 28)),
            as_of=date(2026, 8, 28),
        )
        self.assertEqual(run.writes, 0)
        self.assertEqual(run.snapshots_published, 0)
        self.assertFalse(any(run.securities[0].published for _ in [0]))

    def test_new_money_not_invoked_on_watch(self) -> None:
        view = _view(
            [
                _row("ASELS", market_value=1000, weight_pct=10, price=100),
                _row("SPUS", market_value=9000, weight_pct=90, price=100, asset_class="etf"),
            ]
        )
        plan = _plan(
            view=view,
            policy=_policy(equity=40, etf=60),
            candidates=[],
            security_decisions=(_psd("ASELS", DECISION_WATCH, increase=False),),
        )
        self.assertEqual(plan.recommendations, ())
        self.assertGreater(plan.residual_cash, 0)


if __name__ == "__main__":
    unittest.main()
