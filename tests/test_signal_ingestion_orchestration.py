from __future__ import annotations

import os
import unittest
from datetime import date
from pathlib import Path

from repositories.signal_intelligence_repository import InMemorySignalIntelligenceRepository
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.signal_ingestion_orchestration import run_signal_ingestion_stage
from services.signal_ingestion_policy import (
    ADAPTER_KAP,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_FILINGS_PER_SYMBOL,
    DEFAULT_MAX_SYMBOLS_PER_RUN,
    STATUS_DEFERRED,
    STATUS_FAILED,
    STATUS_NO_NEW_EVENTS,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    resolve_sec_signal_ingestion_enabled,
)
from services.signal_ingestion_universe import (
    apply_symbol_capacity,
    build_signal_ingestion_universe,
)
from services.signal_sec_ingest_fixtures import fixture_crm_single_item_8k


ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "services" / "signal_ingestion_orchestration.py"
SOURCES = ROOT / "services" / "signal_ingestion_sources.py"
POLICY = ROOT / "services" / "signal_ingestion_policy.py"
UNIVERSE = ROOT / "services" / "signal_ingestion_universe.py"
SCRIPT = ROOT / "scripts" / "run_signal_ingestion.py"
WORKFLOW = ROOT / ".github" / "workflows" / "daily_scan.yml"

AS_OF = date(2026, 3, 20)


def _holding(symbol: str, **kwargs):
    row = {
        "symbol": symbol,
        "market": kwargs.pop("market", "US"),
        "asset_class": kwargs.pop("asset_class", "equity"),
        "quantity": kwargs.pop("quantity", 10),
    }
    row.update(kwargs)
    return row


def _candidate(symbol: str, **kwargs):
    row = {
        "symbol": symbol,
        "market": kwargs.pop("market", "US"),
        "asset_class": kwargs.pop("asset_class", "equity"),
        "research_status": kwargs.pop("research_status", "YENI"),
        "research_allowed": kwargs.pop("research_allowed", None),
    }
    row.update(kwargs)
    return row


class FeatureFlagTests(unittest.TestCase):
    def test_flag_default_off(self) -> None:
        env_keys = ("NABI_ENABLE_SEC_SIGNAL_INGESTION", "ENABLE_SEC_SIGNAL_INGESTION")
        saved = {key: os.environ.pop(key, None) for key in env_keys}
        try:
            self.assertFalse(resolve_sec_signal_ingestion_enabled())
            self.assertFalse(resolve_sec_signal_ingestion_enabled(None))
            self.assertFalse(resolve_sec_signal_ingestion_enabled(False))
            os.environ["NABI_ENABLE_SEC_SIGNAL_INGESTION"] = "false"
            self.assertFalse(resolve_sec_signal_ingestion_enabled())
            os.environ["NABI_ENABLE_SEC_SIGNAL_INGESTION"] = "true"
            self.assertTrue(resolve_sec_signal_ingestion_enabled())
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_disabled_stage_makes_no_sec_calls_or_writes(self) -> None:
        calls = {"n": 0}

        def loader(_cik: str):
            calls["n"] += 1
            raise AssertionError("SEC must not be called when flag is OFF")

        report = run_signal_ingestion_stage(
            holdings=[_holding("CRM")],
            enable_sec_signal_ingestion=False,
            submissions_loader=loader,
            cik_by_symbol={"CRM": "1108524"},
        )
        self.assertFalse(report.enabled)
        self.assertEqual(report.sec_submissions_calls, 0)
        self.assertEqual(report.event_writes, 0)
        self.assertEqual(report.evidence_writes, 0)
        self.assertEqual(report.symbols_processed, ())
        self.assertEqual(calls["n"], 0)
        self.assertFalse(report.schedule_activated)


class UniverseConstructionTests(unittest.TestCase):
    def test_holdings_first_then_candidates_stable_order(self) -> None:
        universe = build_signal_ingestion_universe(
            holdings=[_holding("TSLA"), _holding("AAPL"), _holding("crm")],
            candidates=[
                _candidate("NVDA", research_status="INCELEMEDE"),
                _candidate("MSFT", research_status="BEKLEMEDE"),
            ],
        )
        self.assertEqual(universe.holdings, ("AAPL", "CRM", "TSLA"))
        self.assertEqual(universe.candidates, ("MSFT", "NVDA"))
        self.assertEqual(universe.ordered_symbols, ("AAPL", "CRM", "TSLA", "MSFT", "NVDA"))

    def test_blocked_holding_is_monitored(self) -> None:
        universe = build_signal_ingestion_universe(
            holdings=[_holding("CRM", participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL)],
            participation_by_symbol={"CRM": {"status": PARTICIPATION_STATUS_UYGUN_DEGIL}},
        )
        self.assertEqual(universe.holdings, ("CRM",))
        self.assertEqual(universe.members[0].reason, "portfolio_us_equity")

    def test_uygun_degil_candidate_excluded_unless_holding(self) -> None:
        universe = build_signal_ingestion_universe(
            holdings=[_holding("CRM")],
            candidates=[
                _candidate(
                    "NVDA",
                    research_status="INCELEMEDE",
                    participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL,
                ),
                _candidate("AAPL", research_status="INCELEMEDE"),
            ],
            participation_by_symbol={"NVDA": {"status": PARTICIPATION_STATUS_UYGUN_DEGIL}},
        )
        self.assertEqual(universe.candidates, ("AAPL",))
        self.assertIn(("NVDA", "uygun_degil_not_holding"), universe.excluded)

    def test_fund_etf_cash_bist_excluded(self) -> None:
        universe = build_signal_ingestion_universe(
            holdings=[
                _holding("SPUS", asset_class="etf"),
                _holding("CASH", asset_class="cash"),
                _holding("BIMAS", market="BIST"),
                _holding("HLAL", asset_class="etf"),
                _holding("VWRA", asset_class="fund"),
            ],
            candidates=[_candidate("ASELS", market="TR"), _candidate("TF_KATILIM")],
        )
        self.assertEqual(universe.eligible, ())
        reasons = {symbol: reason for symbol, reason in universe.excluded}
        self.assertIn("SPUS", reasons)
        self.assertIn("CASH", reasons)
        self.assertIn("BIMAS", reasons)
        self.assertIn("ASELS", reasons)

    def test_closed_research_candidate_excluded(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[_candidate("MSFT", research_status="TAMAMLANDI")],
        )
        self.assertEqual(universe.candidates, ())
        self.assertIn(("MSFT", "research_not_open"), universe.excluded)

    def test_hisse_abd_candidate_is_us_equity(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[
                _candidate(
                    "NVDA",
                    market="ABD",
                    asset_type="Hisse",
                    asset_class="",
                    cik="1045810",
                    research_status="INCELEMEDE",
                )
            ],
        )
        self.assertEqual(universe.candidates, ("NVDA",))

    def test_incomplete_ticker_tape_candidate_excluded(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[
                _candidate(
                    "AAL",
                    market="ABD",
                    asset_type="Hisse",
                    asset_class="",
                    decision="VERİ EKSİK",
                    research_allowed=None,
                )
            ],
        )
        self.assertEqual(universe.candidates, ())
        self.assertIn(("AAL", "not_active_research"), universe.excluded)


class CategoryPolicyRegressionTests(unittest.TestCase):
    def test_a_holding_uygun_included(self) -> None:
        universe = build_signal_ingestion_universe(
            holdings=[_holding("CRM")],
            participation_by_symbol={"CRM": {"status": PARTICIPATION_STATUS_UYGUN}},
        )
        self.assertEqual(universe.holdings, ("CRM",))
        self.assertEqual(universe.members[0].reason, "portfolio_us_equity")

    def test_b_holding_uygun_degil_included(self) -> None:
        universe = build_signal_ingestion_universe(
            holdings=[_holding("AAPL")],
            participation_by_symbol={"AAPL": {"status": PARTICIPATION_STATUS_UYGUN_DEGIL}},
        )
        self.assertEqual(universe.holdings, ("AAPL",))

    def test_c_research_allowed_and_cik_do_not_create_active_research(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[
                _candidate(
                    "JNJ",
                    research_status="YENI",
                    research_allowed=True,
                    cik="200406",
                    decision=None,
                )
            ],
            participation_by_symbol={"JNJ": {"status": PARTICIPATION_STATUS_UYGUN}},
        )
        self.assertEqual(universe.candidates, ())
        self.assertIn(("JNJ", "not_active_research"), universe.excluded)

    def test_c_jnj_shaped_yeni_uygun_seed_excluded(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[
                _candidate(
                    "JNJ",
                    research_status="YENI",
                    research_allowed=None,
                    decision=None,
                    last_reviewed_at=None,
                    cik=None,
                )
            ],
            participation_by_symbol={"JNJ": {"status": PARTICIPATION_STATUS_UYGUN}},
        )
        self.assertEqual(universe.candidates, ())
        self.assertIn(("JNJ", "not_active_research"), universe.excluded)

    def test_d_yeni_kontrol_et_without_active_research_excluded(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[_candidate("AMZN", research_status="YENI", decision="İZLE")],
            participation_by_symbol={"AMZN": {"status": PARTICIPATION_STATUS_KONTROL_ET}},
        )
        self.assertEqual(universe.candidates, ())
        self.assertIn(("AMZN", "not_active_research"), universe.excluded)

    def test_e_passive_veri_eksik_stub_excluded(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[_candidate("AAL", decision="VERİ EKSİK", research_status="YENI")],
        )
        self.assertEqual(universe.candidates, ())
        self.assertIn(("AAL", "not_active_research"), universe.excluded)

    def test_f_non_holding_uygun_degil_active_research_excluded(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[
                _candidate(
                    "NVDA",
                    research_status="INCELEMEDE",
                    decision="ADAY",
                    participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL,
                )
            ],
            participation_by_symbol={"NVDA": {"status": PARTICIPATION_STATUS_UYGUN_DEGIL}},
        )
        self.assertEqual(universe.candidates, ())
        self.assertIn(("NVDA", "uygun_degil_not_holding"), universe.excluded)

    def test_g_active_research_allowed_participation_included(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[
                _candidate(
                    "NVDA",
                    research_status="INCELEMEDE",
                    decision="ADAY",
                    cik="1045810",
                )
            ],
            participation_by_symbol={"NVDA": {"status": PARTICIPATION_STATUS_KONTROL_ET}},
        )
        self.assertEqual(universe.candidates, ("NVDA",))
        self.assertEqual(universe.members[0].reason, "active_us_equity_research")

    def test_h_tamamlandi_is_terminal_even_with_aday(self) -> None:
        universe = build_signal_ingestion_universe(
            candidates=[
                _candidate(
                    "MSFT",
                    research_status="TAMAMLANDI",
                    decision="ADAY",
                    decision_label="ARAŞTIRMA ADAYI",
                    conviction_score=85.4,
                    cik="789019",
                )
            ],
            participation_by_symbol={"MSFT": {"status": PARTICIPATION_STATUS_KONTROL_ET}},
        )
        self.assertEqual(universe.candidates, ())
        self.assertIn(("MSFT", "research_not_open"), universe.excluded)

    def test_i_etf_fund_bist_cash_excluded(self) -> None:
        universe = build_signal_ingestion_universe(
            holdings=[
                _holding("SPUS", asset_class="etf"),
                _holding("CASH", asset_class="cash"),
                _holding("BIMAS", market="BIST"),
            ],
            candidates=[
                _candidate("HLAL", asset_class="etf", research_status="INCELEMEDE"),
                _candidate("VWRA", asset_class="fund", research_status="INCELEMEDE"),
            ],
        )
        self.assertEqual(universe.eligible, ())


class BoundsAndCapacityTests(unittest.TestCase):
    def test_defaults_are_conservative(self) -> None:
        self.assertEqual(DEFAULT_MAX_SYMBOLS_PER_RUN, 20)
        self.assertEqual(DEFAULT_LOOKBACK_DAYS, 90)
        self.assertEqual(DEFAULT_MAX_FILINGS_PER_SYMBOL, 20)

    def test_capacity_defers_without_silent_loss(self) -> None:
        processed, deferred = apply_symbol_capacity(
            ["AAPL", "CRM", "TSLA", "MSFT", "NVDA"],
            max_symbols_per_run=3,
        )
        self.assertEqual(processed, ("AAPL", "CRM", "TSLA"))
        self.assertEqual(deferred, ("MSFT", "NVDA"))

    def test_stage_capacity_and_stable_order(self) -> None:
        report = run_signal_ingestion_stage(
            holdings=[_holding("TSLA"), _holding("AAPL"), _holding("CRM")],
            candidates=[
                _candidate("NVDA", research_status="INCELEMEDE"),
                _candidate("MSFT", research_status="TEKRAR_BAK"),
            ],
            enable_sec_signal_ingestion=True,
            max_symbols_per_run=3,
            submissions_by_symbol={"AAPL": {}, "CRM": fixture_crm_single_item_8k(), "TSLA": {}},
            cik_by_symbol={"AAPL": "320193", "CRM": "1108524", "TSLA": "1318605"},
            as_of=AS_OF,
        )
        self.assertEqual(report.symbols_processed, ("AAPL", "CRM", "TSLA"))
        self.assertEqual(report.symbols_deferred, ("MSFT", "NVDA"))
        self.assertEqual(report.symbols_requested, ("AAPL", "CRM", "TSLA", "MSFT", "NVDA"))
        deferred_status = [item.status for item in report.per_symbol if item.symbol in report.symbols_deferred]
        self.assertEqual(deferred_status, [STATUS_DEFERRED, STATUS_DEFERRED])


class StageBehaviorTests(unittest.TestCase):
    def test_failure_isolation_and_summary(self) -> None:
        def loader(cik: str):
            if str(cik).lstrip("0") == "320193":
                raise RuntimeError("SEC_TIMEOUT")
            return fixture_crm_single_item_8k()

        report = run_signal_ingestion_stage(
            holdings=[_holding("AAPL"), _holding("CRM")],
            enable_sec_signal_ingestion=True,
            submissions_loader=loader,
            cik_by_symbol={"AAPL": "320193", "CRM": "1108524"},
            as_of=AS_OF,
        )
        by_symbol = {item.symbol: item for item in report.per_symbol}
        self.assertEqual(by_symbol["AAPL"].status, STATUS_FAILED)
        self.assertIn("SEC_TIMEOUT", by_symbol["AAPL"].error or "")
        self.assertIn(by_symbol["CRM"].status, {STATUS_SUCCESS, STATUS_NO_NEW_EVENTS})
        self.assertEqual(report.symbols_failed, 1)
        self.assertEqual(report.symbols_processed, ("AAPL", "CRM"))
        self.assertTrue(report.run_started_at)
        self.assertTrue(report.run_finished_at)

    def test_missing_cik_is_skipped(self) -> None:
        report = run_signal_ingestion_stage(
            holdings=[_holding("CRM"), _holding("ZZZZ")],
            enable_sec_signal_ingestion=True,
            submissions_by_symbol={"CRM": fixture_crm_single_item_8k()},
            cik_by_symbol={"CRM": "1108524"},
            as_of=AS_OF,
        )
        by_symbol = {item.symbol: item for item in report.per_symbol}
        self.assertEqual(by_symbol["ZZZZ"].status, STATUS_SKIPPED)
        self.assertIn(by_symbol["CRM"].status, {STATUS_SUCCESS, STATUS_NO_NEW_EVENTS})

    def test_idempotent_replay_zero_writes(self) -> None:
        repo = InMemorySignalIntelligenceRepository()
        first = run_signal_ingestion_stage(
            holdings=[_holding("CRM")],
            enable_sec_signal_ingestion=True,
            repo=repo,
            submissions_by_symbol={"CRM": fixture_crm_single_item_8k()},
            cik_by_symbol={"CRM": "1108524"},
            as_of=AS_OF,
        )
        replay = run_signal_ingestion_stage(
            holdings=[_holding("CRM")],
            enable_sec_signal_ingestion=True,
            repo=repo,
            submissions_by_symbol={"CRM": fixture_crm_single_item_8k()},
            cik_by_symbol={"CRM": "1108524"},
            as_of=AS_OF,
        )
        self.assertGreaterEqual(first.event_writes, 1)
        self.assertGreaterEqual(first.evidence_writes, 1)
        self.assertEqual(replay.event_writes, 0)
        self.assertEqual(replay.evidence_writes, 0)
        self.assertEqual(replay.symbols_no_new_events, 1)
        self.assertEqual(replay.per_symbol[0].status, STATUS_NO_NEW_EVENTS)

    def test_kap_adapter_is_credential_blocked(self) -> None:
        calls = {"n": 0}

        def loader(_cik: str):
            calls["n"] += 1
            return fixture_crm_single_item_8k()

        report = run_signal_ingestion_stage(
            holdings=[_holding("CRM")],
            adapter=ADAPTER_KAP,
            enable_sec_signal_ingestion=True,
            submissions_loader=loader,
            cik_by_symbol={"CRM": "1108524"},
        )
        self.assertEqual(report.adapter, ADAPTER_KAP)
        self.assertEqual(report.sec_submissions_calls, 0)
        self.assertEqual(report.event_writes, 0)
        self.assertFalse(report.kap_attempted)
        self.assertEqual(calls["n"], 0)
        self.assertIn("credential-blocked", report.message)


class WriteBoundaryTests(unittest.TestCase):
    def test_stage_writes_only_signal_tables(self) -> None:
        write_tokens = (
            "monitor_events",
            "upsert_snapshot",
            "insert_monitor",
            '.table("security_master")',
            '.table("investment_candidates")',
            '.table("participation_assessments")',
            '.table("wealth_positions")',
            '.table("wealth_transactions")',
        )
        for path in (ORCH, SOURCES, POLICY, UNIVERSE, SCRIPT):
            text = path.read_text(encoding="utf-8")
            for token in write_tokens:
                self.assertNotIn(token, text, msg=f"{path.name} must not write via {token}")
        orch = ORCH.read_text(encoding="utf-8")
        self.assertIn("run_sec_signal_ingestion", orch)
        sources = SOURCES.read_text(encoding="utf-8")
        self.assertIn("list_for_user", sources)
        self.assertIn("get_all", sources)
        self.assertIn("list_latest_by_symbol", sources)
        self.assertNotIn("upsert", sources)
        self.assertNotIn(".insert(", sources)
        self.assertNotIn(".update(", sources)

    def test_workflow_hook_exists_and_flag_not_forced_on(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("run_signal_ingestion.py", text)
        self.assertIn("run_daily_scan.py", text)
        self.assertIn('cron: "0 6 * * *"', text)
        self.assertNotIn("NABI_ENABLE_SEC_SIGNAL_INGESTION: true", text.lower())
        self.assertNotIn("ENABLE_SEC_SIGNAL_INGESTION: true", text.lower())
        self.assertIn("vars.ENABLE_SEC_SIGNAL_INGESTION", text)


if __name__ == "__main__":
    unittest.main()
