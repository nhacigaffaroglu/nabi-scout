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


def test_human_approved_fi60_threshold_is_locked_for_research_promotion():
    data = text()
    required = (
        "--threshold-policy config/fund14b/threshold_policy.json",
        'threshold.get("locked") is True',
        'threshold.get("fi_min") == 60.0',
        'threshold.get("source") == "human_decision"',
        'threshold.get("decision_id") == "FUND14B-FI60-2026-09-11"',
        'gate.get("open") is True',
        'gate.get("reasons") == []',
        'gate.get("execution_authority") is False',
        'if float(row["fi_score"]) >= 60.0',
    )
    for item in required:
        assert item in data, item


def test_threshold_policy_file_is_in_workflow_change_paths():
    data = text()
    assert data.count('"config/fund14b/threshold_policy.json"') >= 2


def test_threshold_policy_is_exact_human_approved_fi60_decision():
    import json

    policy = json.loads(
        Path("config/fund14b/threshold_policy.json").read_text(encoding="utf-8")
    )
    assert policy == {
        "locked": True,
        "fi_min": 60.0,
        "source": "human_decision",
        "decision_id": "FUND14B-FI60-2026-09-11",
    }


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
