from pathlib import Path


WORKFLOW = Path(".github/workflows/fund17b_portfolio_context_bridge.yml")


def text():
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists():
    assert WORKFLOW.is_file()


def test_workflow_has_push_and_manual_dispatch():
    data = text()
    assert "push:" in data
    assert "workflow_dispatch:" in data


def test_workflow_is_path_scoped_to_fund17b():
    data = text()
    assert "services/turkiye_fund_portfolio_context_bridge.py" in data
    assert "scripts/run_turkiye_fund_portfolio_context_bridge.py" in data
    assert "tests/test_turkiye_fund_portfolio_context_bridge.py" in data


def test_workflow_runs_bridge_and_fund17_contract_tests():
    data = text()
    assert "tests/test_turkiye_fund_portfolio_context_bridge.py" in data
    assert "tests/test_turkiye_fund_portfolio_fit.py" in data


def test_workflow_has_read_only_repository_permission():
    data = text()
    assert "permissions:" in data
    assert "contents: read" in data


def test_workflow_does_not_use_secrets_or_external_portfolio_source():
    data = text()
    assert "NABI_WEALTH_OS" not in data
    assert "SUPABASE" not in data.upper()
    assert "secrets." not in data


def test_workflow_enforces_research_only_firewall():
    data = text()
    assert '"research_only": True' in data
    assert '"execution_authority": False' in data
    assert '"production_persist": False' in data


def test_workflow_fixture_is_explicitly_not_real_portfolio_data():
    data = text()
    assert "CI_FIXTURE" in data
    assert "not real portfolio data" in data
