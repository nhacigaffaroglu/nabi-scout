from pathlib import Path


WORKFLOW = Path(".github/workflows/fund22_canonical_decision_integration.yml")
SERVICE = Path("services/turkiye_fund_canonical_decision_integration.py")
SERVICE_TEST = Path("tests/test_turkiye_fund_canonical_decision_integration.py")
WORKFLOW_TEST = Path("tests/test_fund22_canonical_decision_integration_workflow.py")


def test_workflow_exists_and_is_path_scoped():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "FUND22 Canonical Decision Integration" in text
    assert "push:" in text
    assert "pull_request:" in text

    for path in (
        str(SERVICE),
        str(SERVICE_TEST),
        str(WORKFLOW_TEST),
        str(WORKFLOW),
    ):
        assert path in text


def test_workflow_permissions_are_read_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:" in text
    assert "contents: read" in text


def test_workflow_runs_focused_tests_and_compile():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert str(SERVICE_TEST) in text
    assert str(WORKFLOW_TEST) in text
    assert "py_compile" in text
    assert str(SERVICE) in text


def test_workflow_validates_research_only_firewall():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'result["research_only"] is True' in text
    assert 'result["execution_authority"] is False' in text
    assert 'result["production_persist"] is False' in text
    assert 'result["decision_winner"] is None' in text
    assert 'result["recommendation"] is None' in text
    assert 'result["allocation"] is None' in text


def test_workflow_preserves_rank_and_does_not_rerank():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'canonical_decision_source_rank' in text
    assert 'decision_evaluation_source_rank' in text
    assert 'decision_rank' in text


def test_workflow_does_not_integrate_new_money_or_recommendation_layers():
    text = WORKFLOW.read_text(encoding="utf-8")

    forbidden = (
        "build_nabi_recommendation(",
        "build_nabi_decision_v3(",
        "evaluate_candidate_investment(",
        "evaluate_fund_new_money_readiness(",
        "allocate_new_money(",
        "supabase",
        "wealth os",
    )

    for token in forbidden:
        assert token not in text.lower()
