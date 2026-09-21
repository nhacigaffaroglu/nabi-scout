from __future__ import annotations

from pathlib import Path

from scripts.run_us_security_intelligence_refresh import parse_args


WORKFLOW = Path(".github/workflows/us_si_readiness.yml")


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_manual_only():
    text = source()
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "cron:" not in text


def test_workflow_scope_is_explicit_and_small():
    text = source()
    assert 'default: "CRM"' in text
    assert "--max-symbols 3" in text
    assert "at most 3 symbols" in text


def test_workflow_restores_but_does_not_save_sec_cache():
    text = source()
    assert "actions/cache/restore@v4" in text
    assert "data/private/sec_company_facts" in text
    assert "actions/cache/save@v4" not in text


def test_workflow_runs_us_si_readiness_script():
    text = source()
    assert "scripts/run_us_security_intelligence_refresh.py" in text
    assert 'args+=(--execute)' in text


def test_workflow_never_enables_live_or_persist_flags():
    text = source()

    run_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("args+=(")
    ]

    assert not any("--live" in line for line in run_lines)
    assert not any("--persist-si" in line for line in run_lines)
    assert not any("--allow-live" in line for line in run_lines)


def test_workflow_validates_zero_write_contract():
    text = source()
    assert 'payload["dry_run"] is True' in text
    assert 'payload["persist_si"] is False' in text
    assert 'payload["allow_live"] is False' in text
    assert 'payload["writes"] == 0' in text
    assert 'payload["published"] == 0' in text
    assert 'payload.get("blocked_writes") == []' in text


def test_provider_dry_run_requires_real_provider_execution():
    text = source()
    assert 'int(payload["provider_calls"]) > 0' in text
    assert '{"WOULD_PUBLISH", "NO_CHANGE"}' in text


def test_plan_mode_requires_zero_provider_calls():
    text = source()
    assert 'int(payload["provider_calls"]) == 0' in text
    assert 'statuses == {"PLANNED"}' in text


def test_cli_defaults_remain_zero_write():
    args = parse_args(["--symbols", "CRM"])

    assert args.execute is False
    assert args.live is False
    assert args.persist_si is False
    assert args.allow_live is False


def test_cli_provider_mode_is_still_not_live():
    args = parse_args(
        [
            "--symbols",
            "CRM",
            "--execute",
            "--max-symbols",
            "3",
        ]
    )

    assert args.execute is True
    assert args.live is False
    assert args.persist_si is False
    assert args.allow_live is False
