from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/fund14a_research_snapshot.yml")


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_present_and_manual_live_only():
    data = text()
    assert "workflow_dispatch:" in data
    assert "\n  schedule:" not in data
    assert "cron:" not in data
    assert "if: github.event_name == 'workflow_dispatch'" in data


def test_workflow_is_read_only_and_has_no_production_credentials_or_persist_flags():
    data = text()
    assert "permissions:\n  contents: read" in data
    forbidden = (
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "--persist-fund-intelligence",
        "--persist-participation",
        "--persist ",
    )
    for token in forbidden:
        assert token not in data, token


def test_workflow_runs_only_fund14a_research_runner_for_live_capture():
    data = text()
    assert "python scripts/run_turkiye_fund_research_snapshot.py" in data
    assert "--live" in data
    assert "--out .artifacts/fund14a/research_snapshot.json" in data
    assert "--run-state .artifacts/fund14a/run_state.json" in data


def test_workflow_validates_exact_research_firewall():
    data = text()
    required = (
        'd.get("schema_version") == "fund14a_research_snapshot_3"',
        'd.get("source_head") == head',
        'd.get("research_only") is True',
        'proof.get("persist") is False',
        'proof.get("production_writes") in ([], None)',
        'proof.get("eight_e_calls", 0) == 0',
        'proof.get("new_money_calls", 0) == 0',
        'proof.get("trades", 0) == 0',
        'proof.get("portfolio_writes", 0) == 0',
        'd.get("activation_safe") is not True',
    )
    for item in required:
        assert item in data


def test_workflow_uploads_evidence_even_on_failed_activation_gate():
    data = text()
    assert "if: always()" in data
    assert "actions/upload-artifact@v4" in data
    assert ".artifacts/fund14a/research_snapshot.json" in data
    assert ".artifacts/fund14a/run_state.json" in data
    assert ".artifacts/fund14a/run.log" in data


def test_push_and_pr_paths_cover_fund14a_contract_surface():
    data = text()
    paths = (
        "scripts/run_turkiye_fund_research_snapshot.py",
        "tests/test_turkiye_fund_research_snapshot.py",
        "services/turkiye_fund_source_capture.py",
        "services/turkiye_fund_broad_capture.py",
        "services/turkiye_fund_scanner.py",
        "services/turkiye_fund_universe_discovery.py",
        "services/turkiye_fund_universe_contract.py",
        "services/turkiye_fund_tefas_history.py",
    )
    for path in paths:
        assert data.count(f'"{path}"') >= 2, path
