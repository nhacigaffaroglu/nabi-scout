from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/fund14b_candidate_artifact.yml")


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_chains_only_from_fund14a_completion():
    data = text()
    assert "workflow_run:" in data
    assert '"FUND14A Research Snapshot"' in data
    assert "completed" in data
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in data
    assert "github.event.workflow_run.conclusion == 'success'" in data


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


def test_checkout_and_candidate_source_pin_use_upstream_head_sha():
    data = text()
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in data
    assert "FUND14A_HEAD_SHA: ${{ github.event.workflow_run.head_sha }}" in data
    assert '--expected-source-head "${FUND14A_HEAD_SHA}"' in data
    assert "--allow-any-source-head" not in data


def test_upstream_firewall_is_revalidated_before_candidate_build():
    data = text()
    required = (
        'd.get("schema_version") == "fund14a_research_snapshot_3"',
        'd.get("source_head") == expected_head',
        'd.get("research_only") is True',
        'd.get("activation_safe") is True',
        'proof.get("persist") is False',
        'proof.get("production_writes") in ([], None)',
        'proof.get("eight_e_calls", 0) == 0',
        'proof.get("new_money_calls", 0) == 0',
        'proof.get("trades", 0) == 0',
        'proof.get("portfolio_writes", 0) == 0',
        'delta.get("manual_review_required") is False',
        'delta.get("added") == []',
        'delta.get("removed") == []',
    )
    for item in required:
        assert item in data, item


def test_threshold_is_deliberately_unlocked_and_promotion_closed():
    data = text()
    required = (
        'threshold.get("locked") is False',
        'threshold.get("fi_min") is None',
        'gate.get("open") is False',
        'gate.get("reasons") == ["THRESHOLD_UNLOCKED"]',
        'gate.get("execution_authority") is False',
        'd.get("promotion_eligible") == []',
    )
    for item in required:
        assert item in data, item
    assert "--threshold-policy" not in data


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


def test_exact_write_firewall_and_evidence_upload():
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
        ".artifacts/fund14b/candidate_artifact.json",
        ".artifacts/fund14b/run.log",
    ):
        assert item in data, item
