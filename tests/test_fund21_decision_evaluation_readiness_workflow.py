from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(
    ".github/workflows/fund21_decision_evaluation_readiness.yml"
)


def workflow_text() -> str:
    assert WORKFLOW.exists()
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists_and_is_path_scoped():
    text = workflow_text()

    assert "name: FUND21 Decision Evaluation Readiness" in text
    assert "workflow_dispatch:" in text
    assert "push:" in text
    assert "pull_request:" in text

    assert (
        "services/turkiye_fund_decision_evaluation_readiness.py"
        in text
    )
    assert (
        "tests/test_turkiye_fund_decision_evaluation_readiness.py"
        in text
    )
    assert (
        "tests/test_fund21_decision_evaluation_readiness_workflow.py"
        in text
    )


def test_workflow_permissions_are_read_only():
    text = workflow_text()

    assert "permissions:" in text
    assert "contents: read" in text

    forbidden = (
        "contents: write",
        "pull-requests: write",
        "actions: write",
        "packages: write",
        "id-token: write",
    )

    for item in forbidden:
        assert item not in text


def test_workflow_runs_focused_fund21_tests():
    text = workflow_text()

    assert (
        "tests/test_turkiye_fund_decision_evaluation_readiness.py"
        in text
    )
    assert (
        "tests/test_fund21_decision_evaluation_readiness_workflow.py"
        in text
    )


def test_workflow_contains_research_firewall_validation():
    text = workflow_text()

    assert 'result["research_only"] is True' in text
    assert 'result["execution_authority"] is False' in text
    assert 'result["production_persist"] is False' in text
    assert 'result["decision_winner"] is None' in text
    assert 'result["recommendation"] is None' in text
    assert 'result["allocation"] is None' in text
    assert 'result["write_proof"] == ZERO_WRITE_PROOF' in text


def test_workflow_proves_fund20_rank_is_preserved():
    text = workflow_text()

    assert 'rows[0]["decision_evaluation_source_rank"] == 2' in text
    assert 'rows[1]["decision_evaluation_source_rank"] == 1' in text

    # High FI score on BBB must not cause FUND21 reranking.
    assert '"fi_score": 99.0' in text
    assert '"fi_score": 70.0' in text


def test_workflow_has_no_execution_integration():
    text = workflow_text().lower()

    forbidden = (
        "supabase",
        "wealth os",
        "allocate_new_money(",
        "evaluate_fund_eight_e_readiness(",
        "evaluate_portfolio_security_decision(",
        "build_nabi_recommendation(",
        "build_nabi_decision_v3(",
    )

    for item in forbidden:
        assert item not in text
