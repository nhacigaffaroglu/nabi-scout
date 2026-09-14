import importlib.util
from pathlib import Path


RUNNER = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_turkiye_fund_portfolio_fit_production.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "fund18_production_runner",
        RUNNER,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_exposes_read_only_production_chain():
    module = _load_runner()

    assert callable(module._default_user_id)
    assert callable(module._canonical_portfolio_view)
    assert callable(module.main)


def test_default_user_id_uses_default_portfolio():
    module = _load_runner()

    class Response:
        data = [{"user_id": "user-1"}]

    class Query:
        def select(self, *args):
            return self

        def eq(self, *args):
            assert args == ("is_default", True)
            return self

        def limit(self, value):
            assert value == 1
            return self

        def execute(self):
            return Response()

    class Client:
        def table(self, name):
            assert name == "wealth_portfolios"
            return Query()

    assert module._default_user_id(Client()) == "user-1"


def test_default_user_id_fails_closed_when_missing():
    module = _load_runner()

    class Response:
        data = []

    class Query:
        def select(self, *args):
            return self

        def eq(self, *args):
            return self

        def limit(self, value):
            return self

        def execute(self):
            return Response()

    class Client:
        def table(self, name):
            return Query()

    try:
        module._default_user_id(Client())
    except SystemExit as exc:
        assert "user_id not found" in str(exc)
    else:
        raise AssertionError("missing default user must fail closed")
