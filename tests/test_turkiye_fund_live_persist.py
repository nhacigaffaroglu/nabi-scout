from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.bist_refresh_contract import REASON_LIVE_UNSAFE, REASON_PILOT_SCOPE
from services.fund_product_contract import LAYER_CASH_LIKE, PILOT_FUND_SYMBOLS, PILOT_TEFAS_FUND_CODES
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.turkiye_fund_persistence import (
    MemoryParticipationAssessmentRepository,
    MemorySecurityIntelligenceSnapshotRepository,
    audit_production_schema_compatibility,
    fund_intelligence_row_from_snapshot,
    participation_row_from_snapshot,
    persist_fund_intelligence_snapshot,
    persist_participation_snapshot,
    schema_compatible,
)
from services.turkiye_fund_refresh_contract import (
    JOB_NAME,
    LAYER_EIGHT_E,
    LAYER_FUND_INTELLIGENCE,
    LAYER_PARTICIPATION,
    OUTCOME_ERROR,
    REASON_FORBIDDEN_LAYER,
    REASON_INVALID_PAYLOAD,
    REASON_PARTICIPATION_WRITE_FAILED,
    STATUS_BLOCKED,
    STATUS_PUBLISHED,
    TABLE_PARTICIPATION_SNAPSHOTS,
    TABLE_SI_SNAPSHOTS,
)
from services.turkiye_fund_refresh_orchestrator import (
    compute_turkiye_fund_snapshots,
    run_turkiye_fund_refresh,
)
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_turkiye_fund_8e import FROZEN_FI

PERSISTENCE = Path("services/turkiye_fund_persistence.py")
ORCHESTRATOR = Path("services/turkiye_fund_refresh_orchestrator.py")
CLI = Path("scripts/run_turkiye_fund_refresh.py")
BIST = Path("services/bist_refresh_contract.py")
BIST_ORCH = Path("services/bist_refresh_orchestrator.py")
US_SI = Path("services/security_intelligence_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
CALCULATED_AT = "2026-08-30T21:00:00+00:00"
PRODUCTION_COMMAND = (
    ".venv/bin/python scripts/run_turkiye_fund_refresh.py "
    "--live --persist-participation --persist-fund-intelligence "
    "--funds AIS,ZPE,IAT"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("run_turkiye_fund_refresh_cli_live", CLI)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _layer(run, fund_code: str, layer: str):
    for fund in run.funds:
        if fund.fund_code == fund_code:
            for row in fund.layers:
                if row.layer == layer:
                    return row
    raise AssertionError(f"missing {fund_code}/{layer}")


def _cli_payload(cli, argv, **kwargs) -> tuple[int, dict]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(argv, **kwargs)
    return code, json.loads(buffer.getvalue())


class TurkiyeFundLivePersistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stamp = CALCULATED_AT
        self.part_repo = MemoryParticipationAssessmentRepository()
        self.fi_repo = MemorySecurityIntelligenceSnapshotRepository()

    def _live(self, **kwargs):
        return run_turkiye_fund_refresh(
            calculated_at=self.stamp,
            cli_live=True,
            persist_participation=True,
            persist_fund_intelligence=True,
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
            **kwargs,
        )

    def test_schema_compatibility_requires_no_migration(self) -> None:
        audit = audit_production_schema_compatibility()
        self.assertFalse(audit["migration_required"])
        self.assertTrue(audit["compatible"])
        self.assertEqual(audit["result"], "COMPATIBLE")
        self.assertEqual(audit["missing_participation_columns"], [])
        self.assertEqual(audit["missing_si_columns"], [])
        self.assertFalse(audit["instrument_market_columns"])
        for code in PILOT_TEFAS_FUND_CODES:
            bundle = compute_turkiye_fund_snapshots(code, calculated_at=self.stamp)
            self.assertTrue(schema_compatible(bundle[LAYER_PARTICIPATION]))
            self.assertTrue(schema_compatible(bundle[LAYER_FUND_INTELLIGENCE]))
            part_row = participation_row_from_snapshot(bundle[LAYER_PARTICIPATION])
            fi_row = fund_intelligence_row_from_snapshot(bundle[LAYER_FUND_INTELLIGENCE])
            self.assertEqual(part_row["status"], PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(part_row["research_allowed"])
            self.assertEqual(part_row["assessment_payload"]["instrument"], "FUND")
            self.assertEqual(part_row["assessment_payload"]["market"], "TR")
            self.assertNotIn("instrument", part_row)
            self.assertNotIn("source_as_of", fi_row)
            self.assertNotIn("calculated_at", fi_row)
            self.assertEqual(fi_row["data_quality"]["instrument"], "FUND")
            self.assertEqual(fi_row["data_quality"]["market"], "TR")

    def test_dry_run_default_and_flag_firewall(self) -> None:
        default = run_turkiye_fund_refresh(calculated_at=self.stamp)
        missing_live = run_turkiye_fund_refresh(
            calculated_at=self.stamp,
            persist_participation=True,
            persist_fund_intelligence=True,
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
        )
        live_only = run_turkiye_fund_refresh(
            calculated_at=self.stamp,
            cli_live=True,
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
        )
        part_only = run_turkiye_fund_refresh(
            calculated_at=self.stamp,
            cli_live=True,
            persist_participation=True,
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
        )
        fi_only = run_turkiye_fund_refresh(
            calculated_at=self.stamp,
            cli_live=True,
            persist_fund_intelligence=True,
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
        )
        for run in (default, missing_live, live_only):
            self.assertTrue(run.dry_run)
            self.assertEqual(run.writes, 0)
            self.assertEqual(run.status, "DRY_RUN")
            self.assertEqual(run.would_publish, 15)
            self.assertEqual(run.published, 0)
            self.assertEqual(run.participation.would_publish, 3)
            self.assertEqual(run.fund_intelligence.would_publish, 3)
        self.assertEqual(part_only.writes, 3)
        self.assertEqual(part_only.participation.published, 3)
        self.assertEqual(part_only.fund_intelligence.published, 0)
        self.assertEqual(part_only.fund_intelligence.would_publish, 3)
        self.assertEqual(fi_only.writes, 3)
        self.assertEqual(fi_only.fund_intelligence.published, 3)
        self.assertEqual(fi_only.participation.published, 0)
        self.assertEqual(len(self.part_repo.rows), 3)
        self.assertEqual(len(self.fi_repo.rows), 3)

    def test_credentials_cannot_enable_writes(self) -> None:
        env = {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/nabi",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            run = run_turkiye_fund_refresh(
                calculated_at=self.stamp,
                dry_run=False,
                persist_participation=True,
                persist_fund_intelligence=True,
                allow_live=True,
                participation_repo=self.part_repo,
                snapshot_repo=self.fi_repo,
            )
        self.assertEqual(run.writes, 0)
        self.assertTrue(run.dry_run)
        self.assertEqual(run.status, "DRY_RUN")
        self.assertEqual(self.part_repo.rows, [])
        self.assertEqual(self.fi_repo.rows, [])
        source = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertNotIn("DATABASE_URL", source)
        self.assertNotIn("os.environ", source)

    def test_pilot_scope_firewall(self) -> None:
        refused = run_turkiye_fund_refresh(
            symbols=("AIS", "ZPE", "IAT", "YYL"),
            calculated_at=self.stamp,
            cli_live=True,
            persist_participation=True,
            persist_fund_intelligence=True,
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
        )
        self.assertEqual(refused.status, "LIVE_BLOCKED")
        self.assertEqual(refused.writes, 0)
        self.assertIn(REASON_PILOT_SCOPE, refused.errors)
        self.assertEqual(self.part_repo.rows, [])
        dry_extra = run_turkiye_fund_refresh(
            symbols=("AIS", "YYL"),
            calculated_at=self.stamp,
        )
        self.assertEqual(dry_extra.status, "DRY_RUN")
        self.assertEqual(dry_extra.writes, 0)

    def test_mocked_live_publish_then_no_change(self) -> None:
        first = self._live()
        self.assertEqual(first.status, "LIVE")
        self.assertFalse(first.dry_run)
        self.assertEqual(first.participation.published, 3)
        self.assertEqual(first.fund_intelligence.published, 3)
        self.assertEqual(first.writes, 6)
        self.assertEqual(len(self.part_repo.rows), 3)
        self.assertEqual(len(self.fi_repo.rows), 3)
        for code, (score, state) in FROZEN_FI.items():
            part = _layer(first, code, LAYER_PARTICIPATION)
            fi = _layer(first, code, LAYER_FUND_INTELLIGENCE)
            eight = _layer(first, code, LAYER_EIGHT_E)
            self.assertEqual(part.status, STATUS_PUBLISHED)
            self.assertEqual(fi.status, STATUS_PUBLISHED)
            self.assertFalse(eight.published)
            stored_fi = next(row for row in self.fi_repo.rows if row["symbol"] == code)
            self.assertEqual(stored_fi["overall_score"], score)
            self.assertEqual(stored_fi["investment_state"], state)
        second = self._live(previous_state=first.next_state)
        self.assertEqual(second.participation.published, 0)
        self.assertEqual(second.fund_intelligence.published, 0)
        self.assertEqual(second.participation.no_change, 3)
        self.assertEqual(second.fund_intelligence.no_change, 3)
        self.assertEqual(second.participation.no_change + second.fund_intelligence.no_change, 6)
        self.assertEqual(second.writes, 0)
        self.assertEqual(len(self.part_repo.rows), 3)
        self.assertEqual(len(self.fi_repo.rows), 3)
        writer_again = self._live()
        self.assertEqual(writer_again.writes, 0)
        self.assertEqual(writer_again.participation.no_change, 3)
        self.assertEqual(writer_again.fund_intelligence.no_change, 3)

    def test_participation_writer_and_fi_writer(self) -> None:
        bundle = compute_turkiye_fund_snapshots("ZPE", calculated_at=self.stamp)
        dry = persist_participation_snapshot(
            self.part_repo, bundle[LAYER_PARTICIPATION], dry_run=True
        )
        self.assertFalse(dry.saved)
        self.assertEqual(self.part_repo.rows, [])
        published = persist_participation_snapshot(
            self.part_repo, bundle[LAYER_PARTICIPATION], dry_run=False
        )
        self.assertTrue(published.saved)
        self.assertEqual(published.row["symbol"], "ZPE")
        self.assertEqual(published.row["semantic_identity"], bundle[LAYER_PARTICIPATION].payload["semantic_identity"])
        duplicate = persist_participation_snapshot(
            self.part_repo, bundle[LAYER_PARTICIPATION], dry_run=False
        )
        self.assertFalse(duplicate.saved)
        self.assertTrue(duplicate.skipped_duplicate)
        self.assertEqual(len(self.part_repo.rows), 1)
        fi_dry = persist_fund_intelligence_snapshot(
            self.fi_repo, bundle[LAYER_FUND_INTELLIGENCE], dry_run=True
        )
        self.assertFalse(fi_dry.saved)
        fi_pub = persist_fund_intelligence_snapshot(
            self.fi_repo, bundle[LAYER_FUND_INTELLIGENCE], dry_run=False
        )
        self.assertTrue(fi_pub.saved)
        fi_dup = persist_fund_intelligence_snapshot(
            self.fi_repo, bundle[LAYER_FUND_INTELLIGENCE], dry_run=False
        )
        self.assertTrue(fi_dup.skipped_duplicate)
        self.assertEqual(len(self.fi_repo.rows), 1)

    def test_participation_failure_blocks_fi_same_fund(self) -> None:
        self.part_repo.fail_symbols.add("AIS")
        run = self._live()
        ais_part = _layer(run, "AIS", LAYER_PARTICIPATION)
        ais_fi = _layer(run, "AIS", LAYER_FUND_INTELLIGENCE)
        self.assertEqual(ais_part.status, OUTCOME_ERROR)
        self.assertEqual(ais_fi.status, STATUS_BLOCKED)
        self.assertEqual(ais_fi.reason, REASON_PARTICIPATION_WRITE_FAILED)
        self.assertFalse(ais_fi.published)
        self.assertEqual(_layer(run, "ZPE", LAYER_PARTICIPATION).status, STATUS_PUBLISHED)
        self.assertEqual(_layer(run, "ZPE", LAYER_FUND_INTELLIGENCE).status, STATUS_PUBLISHED)
        self.assertEqual(_layer(run, "IAT", LAYER_PARTICIPATION).status, STATUS_PUBLISHED)
        self.assertEqual(_layer(run, "IAT", LAYER_FUND_INTELLIGENCE).status, STATUS_PUBLISHED)
        self.assertEqual(run.participation.errors, 1)
        self.assertEqual(run.fund_intelligence.published, 2)
        self.assertTrue(run.errors)
        self.assertEqual(run.status, "ERROR")
        self.assertEqual([row["symbol"] for row in self.part_repo.rows], ["ZPE", "IAT"])
        self.assertEqual(sorted(row["symbol"] for row in self.fi_repo.rows), ["IAT", "ZPE"])

    def test_fi_failure_does_not_corrupt_participation(self) -> None:
        self.fi_repo.fail_symbols.add("ZPE")
        run = self._live()
        self.assertEqual(_layer(run, "ZPE", LAYER_PARTICIPATION).status, STATUS_PUBLISHED)
        self.assertEqual(_layer(run, "ZPE", LAYER_FUND_INTELLIGENCE).status, OUTCOME_ERROR)
        self.assertEqual(_layer(run, "AIS", LAYER_FUND_INTELLIGENCE).status, STATUS_PUBLISHED)
        self.assertEqual(_layer(run, "IAT", LAYER_FUND_INTELLIGENCE).status, STATUS_PUBLISHED)
        self.assertEqual({row["symbol"] for row in self.part_repo.rows}, {"AIS", "ZPE", "IAT"})
        self.assertEqual({row["symbol"] for row in self.fi_repo.rows}, {"AIS", "IAT"})
        self.assertEqual(run.status, "ERROR")
        self.assertTrue(run.errors)

    def test_database_unavailable_and_invalid_payload(self) -> None:
        self.part_repo.unavailable = True
        down = self._live(symbols=("AIS",))
        self.assertEqual(down.writes, 0)
        self.assertEqual(_layer(down, "AIS", LAYER_PARTICIPATION).status, OUTCOME_ERROR)
        self.assertEqual(_layer(down, "AIS", LAYER_FUND_INTELLIGENCE).reason, REASON_PARTICIPATION_WRITE_FAILED)
        bundle = compute_turkiye_fund_snapshots("IAT", calculated_at=self.stamp)
        broken = replace(
            bundle[LAYER_PARTICIPATION],
            payload={**bundle[LAYER_PARTICIPATION].payload, "status": "", "semantic_identity": ""},
        )
        invalid = persist_participation_snapshot(self.part_repo, broken, dry_run=False)
        self.assertTrue(invalid.invalid)
        self.assertEqual(invalid.message, REASON_INVALID_PAYLOAD)
        eight = persist_fund_intelligence_snapshot(
            self.fi_repo, bundle[LAYER_EIGHT_E], dry_run=False
        )
        self.assertTrue(eight.invalid)
        self.assertEqual(self.fi_repo.rows, [])

    def test_ais_cash_like_persisted_and_eight_e_not_written(self) -> None:
        run = self._live(symbols=("AIS",))
        self.assertEqual(run.writes, 2)
        row = self.fi_repo.rows[0]
        self.assertEqual(row["data_quality"]["economic_exposure"]["primary_exposure"], LAYER_CASH_LIKE)
        encoded = json.dumps(row, default=str)
        self.assertNotIn('"primary_exposure": "cash"', encoded)
        self.assertNotIn('"primary_exposure": "CASH"', encoded)
        self.assertNotIn("ASSET_CLASS_CASH", encoded)
        self.assertEqual(self.part_repo.TABLE, TABLE_PARTICIPATION_SNAPSHOTS)
        self.assertEqual(self.fi_repo.TABLE, TABLE_SI_SNAPSHOTS)
        persist_source = PERSISTENCE.read_text(encoding="utf-8")
        self.assertNotIn("eight_e", persist_source)
        self.assertNotIn("LAYER_EIGHT_E", persist_source)
        self.assertNotIn("allocate_new_money", persist_source)

    def test_cli_firewall_and_dry_run_uat(self) -> None:
        cli = _load_cli()
        mode_default = cli.resolve_execution_mode(
            SimpleNamespace(
                live=False,
                persist_participation=False,
                persist_fund_intelligence=False,
                persist_economic_exposure=False,
                persist_decisions=False,
                allow_live=False,
                allow_broad=False,
            )
        )
        self.assertTrue(mode_default["dry_run"])
        self.assertFalse(mode_default["persist_participation"])
        persist_without_live = cli.resolve_execution_mode(
            SimpleNamespace(
                live=False,
                persist_participation=True,
                persist_fund_intelligence=True,
                persist_economic_exposure=False,
                persist_decisions=False,
                allow_live=True,
                allow_broad=False,
            )
        )
        self.assertTrue(persist_without_live["dry_run"])
        self.assertFalse(persist_without_live["persist_participation"])
        self.assertFalse(persist_without_live["persist_fund_intelligence"])
        with patch.object(cli, "attach_production_repos", side_effect=AssertionError("attach_called")):
            code, payload = _cli_payload(cli, [])
            self.assertEqual(code, 0)
            self.assertEqual(payload["writes"], 0)
            self.assertEqual(payload["status"], "DRY_RUN")
            self.assertIn(payload["participation"]["would_publish"], {0, 3})
            self.assertIn(payload["fund_intelligence"]["would_publish"], {0, 3})
            self.assertTrue(
                payload["participation"]["would_publish"] + payload["participation"]["no_change"] == 3
            )
            self.assertTrue(
                payload["fund_intelligence"]["would_publish"] + payload["fund_intelligence"]["no_change"]
                == 3
            )
            self.assertEqual(cli.main(["--persist-participation", "--persist-fund-intelligence"]), 0)
            self.assertEqual(cli.main(["--live"]), 0)
            env = {"DATABASE_URL": "postgresql://user:pass@localhost:5432/nabi"}
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(
                    cli.main(["--persist-participation", "--persist-fund-intelligence"]),
                    0,
                )
        code, blocked = _cli_payload(cli, ["--persist-decisions"])
        self.assertEqual(code, 1)
        self.assertEqual(blocked["writes"], 0)
        self.assertEqual(blocked["errors"], [REASON_FORBIDDEN_LAYER])
        code, live_unsafe = _cli_payload(
            cli,
            ["--live", "--persist-participation", "--persist-fund-intelligence"],
            attach_repos=lambda **_: (_ for _ in ()).throw(RuntimeError(REASON_LIVE_UNSAFE)),
        )
        self.assertEqual(code, 1)
        self.assertEqual(live_unsafe["writes"], 0)
        self.assertIn(REASON_LIVE_UNSAFE, live_unsafe["errors"])

    def test_cli_mocked_live_does_not_touch_production(self) -> None:
        cli = _load_cli()
        part = MemoryParticipationAssessmentRepository()
        fi = MemorySecurityIntelligenceSnapshotRepository()

        def attach(**_kwargs):
            return None, fi, part

        with tempfile.TemporaryDirectory() as tmp:
            live_argv = [
                "--live",
                "--persist-participation",
                "--persist-fund-intelligence",
                "--funds",
                "AIS,ZPE,IAT",
                "--state-file",
                str(Path(tmp) / "state.json"),
            ]
            code, payload = _cli_payload(cli, live_argv, attach_repos=attach)
            self.assertEqual(code, 0)
            self.assertEqual(payload["writes"], 6)
            self.assertEqual(payload["participation"]["published"], 3)
            self.assertEqual(payload["fund_intelligence"]["published"], 3)
            self.assertEqual(payload["cli_live"], True)
            self.assertEqual(payload["job_name"], JOB_NAME)
            self.assertEqual(payload["fund_codes"], ["AIS", "ZPE", "IAT"])
            self.assertEqual(len(part.rows), 3)
            self.assertEqual(len(fi.rows), 3)
            code2, second = _cli_payload(cli, live_argv, attach_repos=attach)
            self.assertEqual(code2, 0)
            self.assertEqual(second["writes"], 0)
            self.assertEqual(second["participation"]["no_change"], 3)
            self.assertEqual(second["fund_intelligence"]["no_change"], 3)

    def test_cli_pilot_scope_and_funds_alias(self) -> None:
        cli = _load_cli()
        self.assertEqual(cli.resolve_fund_codes(SimpleNamespace(funds="AIS,ZPE,IAT", symbols="")), ["AIS", "ZPE", "IAT"])
        code, payload = _cli_payload(
            cli,
            ["--live", "--persist-participation", "--funds", "AIS,YYL"],
            attach_repos=lambda **_: (None, self.fi_repo, self.part_repo),
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload["writes"], 0)
        self.assertEqual(payload["errors"], [REASON_PILOT_SCOPE])

    def test_observability_and_production_command_not_executed(self) -> None:
        run = self._live()
        payload = run.to_dict()
        for key in (
            "run_id",
            "job_name",
            "started_at",
            "finished_at",
            "status",
            "dry_run",
            "cli_live",
            "fund_codes",
            "participation",
            "fund_intelligence",
            "writes",
        ):
            self.assertIn(key, payload)
        for layer in ("participation", "fund_intelligence"):
            for field in ("processed", "published", "would_publish", "no_change", "blocked", "errors"):
                self.assertIn(field, payload[layer])
        self.assertIn("--live", PRODUCTION_COMMAND)
        self.assertIn("--persist-participation", PRODUCTION_COMMAND)
        self.assertIn("--persist-fund-intelligence", PRODUCTION_COMMAND)
        self.assertIn("--funds AIS,ZPE,IAT", PRODUCTION_COMMAND)
        self.assertNotIn("os.system", PERSISTENCE.read_text(encoding="utf-8"))

    def test_new_money_hybrid_eight_e_and_regression(self) -> None:
        for path in (PERSISTENCE, ORCHESTRATOR, CLI):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("allocate_new_money", source)
            self.assertNotIn("enable_hybrid_exposure_allocation", source)
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        self.assertTrue(callable(allocate_new_money))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        with patch(
            "services.wealth_new_money_allocation.allocate_new_money",
            side_effect=AssertionError("new_money_called"),
        ):
            run = self._live()
        self.assertEqual(run.writes, 6)
        from services.fund_intelligence_engine import evaluate_official_fund_intelligence

        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        sp = default_official_sp_funds_provider()
        tefas = default_tefas_fund_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertTrue(sp.supports(symbol))
            self.assertFalse(tefas.supports(symbol))
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertIn("persist_si", BIST_ORCH.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        for code, (score, state) in FROZEN_FI.items():
            bundle = compute_turkiye_fund_snapshots(code, calculated_at=self.stamp)
            self.assertEqual(bundle[LAYER_FUND_INTELLIGENCE].payload["overall_score"], score)
            self.assertEqual(bundle[LAYER_FUND_INTELLIGENCE].payload["investment_state"], state)
            self.assertEqual(bundle[LAYER_PARTICIPATION].payload["status"], PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(bundle[LAYER_PARTICIPATION].payload["research_allowed"])
            self.assertEqual(bundle[LAYER_EIGHT_E].payload["decision"], "WATCH")
            self.assertFalse(bundle[LAYER_EIGHT_E].payload["increase_allowed"])


if __name__ == "__main__":
    unittest.main()
