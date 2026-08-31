from __future__ import annotations

import unittest
from pathlib import Path

from services.bist_official_participation_contract import WATCHER_COMPARE_FIELDS
from services.bist_official_participation_policy import official_decision_compare_key
from services.bist_thb_history import DEFAULT_CACHE_DIR, date_is_cached
from services.security_intelligence_publish import publish_canonical_security_intelligence


WORKFLOWS = Path(".github/workflows")
SCRIPTS = Path("scripts")
PUBLISH = Path("services/security_intelligence_publish.py")


class ScheduledJobInventoryTests(unittest.TestCase):
    def test_github_actions_schedules_exist(self) -> None:
        expected = {
            "daily_scan.yml": 'cron: "0 6 * * *"',
            "daily_universe_expansion.yml": 'cron: "0 3 * * *"',
            "daily_monitor.yml": 'cron: "30 7 * * *"',
            "daily_fx_refresh.yml": 'cron: "0 4 * * *"',
            "daily_wealth_snapshot.yml": 'cron: "30 6 * * *"',
            "daily_fund_holdings_refresh.yml": 'cron: "30 5 * * *"',
            "daily_bist_refresh.yml": 'cron: "30 15 * * 1-5"',
            "daily_turkiye_fund_refresh.yml": 'cron: "0 16 * * 1-5"',
        }
        for name, cron in expected.items():
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertIn(cron, text, name)

    def test_no_paid_or_second_engine_in_bist_workflow(self) -> None:
        for path in WORKFLOWS.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("publish_canonical_security_intelligence", text, path.name)
            if path.name != "daily_bist_refresh.yml":
                self.assertNotIn("kafif", text.lower(), path.name)
                self.assertNotIn("thb_history", text, path.name)
                self.assertNotIn("run_bist_refresh.py", text, path.name)
        for path in SCRIPTS.glob("run_daily_*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("publish_canonical_security_intelligence", text, path.name)
        bist = (WORKFLOWS / "daily_bist_refresh.yml").read_text(encoding="utf-8")
        self.assertIn("run_bist_refresh.py", bist)
        self.assertIn('cron: "30 15 * * 1-5"', bist)
        self.assertNotIn("FMP_API_KEY", bist)
        turkiye = (WORKFLOWS / "daily_turkiye_fund_refresh.yml").read_text(encoding="utf-8")
        self.assertIn("run_turkiye_fund_refresh.py", turkiye)
        self.assertIn("--live", turkiye)
        self.assertIn("--persist-fund-intelligence", turkiye)
        self.assertIn("--persist-participation", turkiye)
        self.assertNotIn("run_bist_refresh.py", turkiye)
        self.assertNotIn("FMP_API_KEY", turkiye)
        self.assertNotIn("post_transaction", turkiye)
        self.assertNotIn("allocate_new_money", turkiye)

    def test_kafif_compare_key_uses_notification_id(self) -> None:
        self.assertIn("source_notification_id", WATCHER_COMPARE_FIELDS)
        self.assertIn("source_period", WATCHER_COMPARE_FIELDS)
        self.assertNotIn("kafif_submitted_at", WATCHER_COMPARE_FIELDS)
        self.assertNotIn("correction", WATCHER_COMPARE_FIELDS)

    def test_same_kafif_notification_compare_key_is_idempotent(self) -> None:
        from types import SimpleNamespace

        evidence = SimpleNamespace(
            symbol="EQBISTX",
            nabi_participation_shadow="Uygun",
            decision_authority="BIST_OFFICIAL",
            provenance={
                "source_membership_state": "MEMBER",
                "membership_as_of": "2026-08-31",
                "source_notification_id": "nid-1",
                "source_period": "FY",
                "source_financial_year": "2025",
                "kafif_submitted_at": "2026-02-01",
            },
        )
        first = official_decision_compare_key(evidence)
        second = official_decision_compare_key(evidence)
        self.assertEqual(first, second)
        self.assertEqual(first["source_notification_id"], "nid-1")
        same_period_other_id = official_decision_compare_key(
            SimpleNamespace(
                symbol="EQBISTX",
                nabi_participation_shadow="Uygun",
                decision_authority="BIST_OFFICIAL",
                provenance={
                    **evidence.provenance,
                    "source_notification_id": "nid-2",
                    "kafif_submitted_at": "2026-03-01",
                },
            )
        )
        self.assertNotEqual(first["source_notification_id"], same_period_other_id["source_notification_id"])

    def test_thb_incremental_skips_cached_date(self) -> None:
        from datetime import date

        from services.bist_thb_history import ThbHistoryCache, fetch_thb_trading_date

        cache = ThbHistoryCache(root=Path("tests/fixtures/_thb_cursor_unused"))
        trading = date(2026, 8, 28)
        cache.known_dates[trading.isoformat()] = "ok"
        self.assertTrue(date_is_cached(cache, trading))
        calls: list[int] = []

        def opener(*_args, **_kwargs):
            calls.append(1)
            raise AssertionError("cached date must not redownload")

        bulletin = fetch_thb_trading_date(trading, cache=cache, opener=opener)
        self.assertIsNone(bulletin)
        self.assertEqual(calls, [])
        self.assertEqual(DEFAULT_CACHE_DIR, Path(".cache/bist_thb_history"))

    def test_si_publish_exists_but_is_not_scheduled(self) -> None:
        self.assertTrue(callable(publish_canonical_security_intelligence))
        self.assertNotIn("cron", PUBLISH.read_text(encoding="utf-8"))

    def test_bist_refresh_cli_defaults_zero_write(self) -> None:
        from scripts.run_bist_refresh import parse_args, resolve_execution_mode

        cli = (SCRIPTS / "run_bist_refresh.py").read_text(encoding="utf-8")
        self.assertIn("run_bist_refresh", cli)
        mode = resolve_execution_mode(parse_args([]))
        self.assertTrue(mode["dry_run"])
        self.assertFalse(mode["persist_si"])
        self.assertFalse(mode["persist_participation"])


if __name__ == "__main__":
    unittest.main()
