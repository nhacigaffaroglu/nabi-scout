from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_us_security_intelligence_refresh import (
    SiWriteGuard,
    parse_args,
)


WORKFLOW = Path(".github/workflows/us_si_controlled_publish.yml")


class FakeTable:
    def upsert(self, *_args, **_kwargs):
        return "allowed"

    def update(self, *_args, **_kwargs):
        return "should-not-run"


class FakeClient:
    def table(self, _name):
        return FakeTable()


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_manual_only():
    text = source()

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "cron:" not in text


def test_workflow_requires_exact_single_symbol_and_confirmation():
    text = source()

    assert "exactly one symbol" in text.lower()
    assert "--max-symbols 1" in text
    assert "PUBLISH_SI_SNAPSHOT" in text
    assert "PUBLISH_AUTHORIZATION=PASS" in text


def test_workflow_enables_live_publish_only_in_controlled_surface():
    text = source()

    assert "--execute" in text
    assert "--live" in text
    assert "--persist-si" in text
    assert "--allow-live" in text


def test_workflow_restores_but_does_not_save_sec_cache():
    text = source()

    assert "actions/cache/restore@v4" in text
    assert "data/private/sec_company_facts" in text
    assert "actions/cache/save@v4" not in text


def test_workflow_requires_only_snapshot_upsert_write():
    text = source()

    assert 'payload.get("blocked_writes") == []' in text
    assert '"security_intelligence_snapshots.upsert"' in text
    assert 'status in {"PUBLISHED", "NO_CHANGE"}' in text
    assert "writes in {0, 1}" in text


def test_cli_flags_support_explicit_controlled_publish():
    args = parse_args(
        [
            "--symbols",
            "CRM",
            "--max-symbols",
            "1",
            "--execute",
            "--live",
            "--persist-si",
            "--allow-live",
        ]
    )

    assert args.symbols == "CRM"
    assert args.max_symbols == 1
    assert args.execute is True
    assert args.live is True
    assert args.persist_si is True
    assert args.allow_live is True


def test_write_guard_records_allowed_snapshot_upsert():
    guard = SiWriteGuard(FakeClient())

    result = guard.table(
        "security_intelligence_snapshots"
    ).upsert({"symbol": "CRM"})

    assert result == "allowed"
    assert guard.allowed_write_attempts == [
        "security_intelligence_snapshots.upsert"
    ]
    assert guard.blocked == []


def test_write_guard_blocks_other_database_writes():
    guard = SiWriteGuard(FakeClient())

    with pytest.raises(
        RuntimeError,
        match=r"blocked write investment_candidates.update",
    ):
        guard.table(
            "investment_candidates"
        ).update({"symbol": "CRM"})

    assert guard.blocked == [
        "investment_candidates.update"
    ]
    assert guard.allowed_write_attempts == []
