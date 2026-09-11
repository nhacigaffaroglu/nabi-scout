from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/fund15_category_research.yml")


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_chains_only_from_fund14b_completion():
    data = text()
    assert "workflow_run:" in data
    assert '"FUND14B Candidate Artifact"' in data
    assert "completed" in data
    assert "github.event.workflow_run.event == 'workflow_run'" in data
    assert "github.event.workflow_run.conclusion == 'success'" in data


def test_workflow_filters_push_only_fund14b_runs_from_live_build():
    data = text()
    assert "github.event_name == 'workflow_run'" in data
    assert "github.event.workflow_run.event == 'workflow_run'" in data
    assert "github.event.workflow_run.event == 'push'" not in data


def test_workflow_has_no_schedule_or_direct_live_capture():
    data = text()
    assert "\n  schedule:" not in data
    assert "cron:" not in data
    assert "run_turkiye_fund_research_snapshot.py" not in data


def test_permissions_are_read_only_and_cross_run_artifact_read_is_explicit():
    data = text()
    assert "permissions:\n  contents: read\n  actions: read" in data
    assert "actions/download-artifact@v5" in data
    assert "run-id: ${{ github.event.workflow_run.id }}" in data
    assert "github-token: ${{ secrets.GITHUB_TOKEN }}" in data


def test_checkout_and_upstream_provenance_use_exact_fund14b_head_sha():
    data = text()
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in data
    assert "FUND14B_HEAD_SHA: ${{ github.event.workflow_run.head_sha }}" in data
    assert 'source.get("source_head") == expected_head' in data


def test_upstream_fund14b_locked_threshold_and_firewall_are_revalidated():
    data = text()
    required = (
        'd.get("schema_version") == "fund14b_candidate_artifact_4"',
        'd.get("research_only") is True',
        'd.get("execution_authority") is False',
        'd.get("production_persist") is False',
        'threshold.get("locked") is True',
        'threshold.get("fi_min") == 60.0',
        'threshold.get("source") == "human_decision"',
        'threshold.get("decision_id") == "FUND14B-FI60-2026-09-11"',
        'gate.get("open") is True',
        'gate.get("reasons") == []',
        'gate.get("meaning") == "research_candidate_promotion_only"',
        'gate.get("execution_authority") is False',
    )
    for item in required:
        assert item in data, item


def test_fund15_output_explicitly_forbids_cross_category_winner_and_execution():
    data = text()
    required = (
        'd.get("schema_version") == "fund15_category_research_artifact_1"',
        'd.get("research_only") is True',
        'd.get("execution_authority") is False',
        'd.get("production_persist") is False',
        'd.get("cross_category_winner") is None',
        'd.get("cross_category_composite_score") is None',
    )
    for item in required:
        assert item in data, item


def test_no_production_credentials_or_persistence_flags():
    data = text()
    for forbidden in (
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "--persist-fund-intelligence",
        "--persist-participation",
        "--persist ",
    ):
        assert forbidden not in data, forbidden


def test_exact_zero_write_firewall_and_evidence_upload():
    data = text()
    for item in (
        '"production_writes": 0',
        '"trade_actions": 0',
        '"orders": 0',
        '"portfolio_writes": 0',
        '"eight_e_calls": 0',
        '"new_money_calls": 0',
        "if: always()",
        "actions/upload-artifact@v4",
        ".artifacts/fund15/category_research_artifact.json",
        ".artifacts/fund15/run.log",
    ):
        assert item in data, item
