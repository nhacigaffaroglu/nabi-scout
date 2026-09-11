from pathlib import Path


WORKFLOW = Path(
    ".github/workflows/fund18_portfolio_fit_research.yml"
)


def text():
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists():
    assert WORKFLOW.exists()


def test_has_push_and_manual_dispatch():
    value = text()
    assert "push:" in value
    assert "workflow_dispatch:" in value


def test_is_path_scoped_to_fund18():
    value = text()
    assert "turkiye_fund_portfolio_fit_research.py" in value
    assert "test_fund18_portfolio_fit_research_workflow.py" in value


def test_runs_fund18_and_upstream_contract_tests():
    value = text()
    assert "test_turkiye_fund_portfolio_fit_research.py" in value
    assert "test_run_turkiye_fund_portfolio_fit_research.py" in value
    assert "test_turkiye_fund_portfolio_fit.py" in value
    assert "test_turkiye_fund_portfolio_context_bridge.py" in value


def test_permissions_are_read_only():
    value = text()
    assert "permissions:" in value
    assert "contents: read" in value


def test_no_secrets_or_external_portfolio_source():
    value = text()
    assert "secrets." not in value
    assert "SUPABASE" not in value
    assert "NABI_WEALTH_OS" not in value


def test_firewall_guards_are_explicit():
    value = text()
    assert 'result["research_only"] is True' in value
    assert 'result["execution_authority"] is False' in value
    assert 'result["production_persist"] is False' in value
    assert 'result["portfolio_fit_winner"] is None' in value
    assert 'result["portfolio_fit_composite_score"] is None' in value
    assert 'result["recommendation"] is None' in value


def test_fixture_is_explicitly_synthetic():
    value = text()
    assert "CI fixture only; not real portfolio data." in value
    assert "Synthetic CI fixture only; not investment advice." in value
