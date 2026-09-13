from pathlib import Path


WORKFLOW = Path(
    ".github/workflows/fund20_decision_candidate_ranking.yml"
)


def text():
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists():
    assert WORKFLOW.exists()


def test_has_push_and_manual_dispatch():
    value = text()

    assert "push:" in value
    assert "workflow_dispatch:" in value


def test_is_path_scoped_to_fund20():
    value = text()

    assert (
        "turkiye_fund_decision_candidate_ranking.py"
        in value
    )

    assert (
        "test_turkiye_fund_decision_candidate_ranking.py"
        in value
    )

    assert (
        "test_fund20_decision_candidate_ranking_workflow.py"
        in value
    )


def test_runs_fund20_contract_tests():
    value = text()

    assert (
        "test_turkiye_fund_decision_candidate_ranking.py"
        in value
    )

    assert (
        "test_fund20_decision_candidate_ranking_workflow.py"
        in value
    )


def test_permissions_are_read_only():
    value = text()

    assert "permissions:" in value
    assert "contents: read" in value


def test_no_secrets_or_external_sources():
    value = text()

    assert "secrets." not in value
    assert "SUPABASE" not in value
    assert "NABI_WEALTH_OS" not in value


def test_portfolio_fit_precedes_fi_score():
    value = text()

    assert (
        'rows["BBB"]["decision_rank"] == 1'
        in value
    )

    assert (
        'rows["AAA"]["decision_rank"] == 2'
        in value
    )


def test_rank_one_is_not_decision_authority():
    value = text()

    assert 'result["decision_winner"] is None' in value
    assert 'result["recommendation"] is None' in value
    assert 'result["allocation"] is None' in value

    assert 'result["execution_authority"] is False' in value
    assert 'result["production_persist"] is False' in value

    assert 'result["write_proof"] == zero' in value


def test_no_execution_fields():
    value = text()

    assert '"trade" not in leader' in value
    assert '"order" not in leader' in value
    assert '"eight_e_action" not in leader' in value
    assert '"new_money_action" not in leader' in value
    assert '"target_weight" not in leader' in value
    assert '"quantity" not in leader' in value
