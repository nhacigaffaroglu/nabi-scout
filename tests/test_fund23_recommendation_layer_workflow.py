from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(
    ".github/workflows/fund23_recommendation_layer.yml"
)

SERVICE = Path(
    "services/turkiye_fund_recommendation_layer.py"
)


def test_fund23_workflow_exists() -> None:
    assert WORKFLOW.exists()


def test_fund23_workflow_is_path_scoped() -> None:
    text = WORKFLOW.read_text()

    required_paths = (
        "services/turkiye_fund_recommendation_layer.py",
        "tests/test_turkiye_fund_recommendation_layer.py",
        "tests/test_fund23_recommendation_layer_workflow.py",
        ".github/workflows/fund23_recommendation_layer.yml",
    )

    for path in required_paths:
        assert path in text


def test_fund23_workflow_is_read_only() -> None:
    text = WORKFLOW.read_text()

    assert "permissions:" in text
    assert "contents: read" in text


def test_fund23_workflow_runs_tests_and_compile() -> None:
    text = WORKFLOW.read_text()

    assert (
        "tests/test_turkiye_fund_recommendation_layer.py"
        in text
    )
    assert (
        "tests/test_fund23_recommendation_layer_workflow.py"
        in text
    )
    assert "python -m pytest" in text
    assert "python -m py_compile" in text


def test_fund23_workflow_validates_research_firewall() -> None:
    text = WORKFLOW.read_text()

    required_assertions = (
        'result["research_only"] is True',
        'result["execution_authority"] is False',
        'result["production_persist"] is False',
        'result["decision_winner"] is None',
        'result["recommended_symbol"] is None',
        'result["allocation"] is None',
        'result["target_weight"] is None',
        'result["quantity"] is None',
        'result["trade"] is None',
        'result["order"] is None',
    )

    for assertion in required_assertions:
        assert assertion in text


def test_fund23_service_has_no_downstream_authority_calls() -> None:
    text = SERVICE.read_text()

    forbidden = (
        "build_nabi_recommendation(",
        "build_nabi_decision_v3(",
        "evaluate_candidate_investment(",
        "evaluate_fund_new_money_readiness(",
        "allocate_new_money(",
        "record_recommendation(",
        "supabase",
        "wealth os",
    )

    for token in forbidden:
        assert token.lower() not in text.lower()


def test_fund23_service_preserves_canonical_authority() -> None:
    text = SERVICE.read_text()

    assert "PORTFOLIO_SECURITY_DECISIONS" in text
    assert '"CANONICAL_8E_DECISION"' in text
    assert (
        '"recommendation_action": row["canonical_decision"]'
        in text
    )


def test_fund23_service_preserves_rank_provenance() -> None:
    text = SERVICE.read_text()

    assert "canonical_decision_source_rank" in text
    assert "decision_evaluation_source_rank" in text
    assert "decision_rank" in text
    assert "recommendation_source_rank" in text
