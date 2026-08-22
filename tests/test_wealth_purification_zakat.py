from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from components.wealth_purification_zakat_ui import (
    render_purification_zakat_center,
    scenario_from_session,
)
from services.wealth_brief_presentation import build_wealth_brief
from services.wealth_contract import TXN_TYPE_DEPOSIT, TXN_TYPE_DIVIDEND
from services.wealth_purification_zakat import (
    BRIEF_MISSING,
    BRIEF_READY,
    CASH_UNAVAILABLE,
    MISSING_PURIFICATION_RATIO,
    MISSING_ZAKAT_ELIGIBILITY,
    PARTIAL_VALUATION_LIMITATION,
    STATUS_MISSING_INPUT,
    PurificationBasis,
    PurificationZakatScenario,
    ProductAssumption,
    calculate_purification_zakat,
)
from services.wealth_purification_zakat_presentation import DISCLAIMER
from tests.test_portfolio_decision_center_ui import ACCOUNT, _live_like_decision
from tests.test_portfolio_decision_intelligence import (
    _partial_bist_view,
    _row,
    _view,
)
from tests.test_wealth_brief_ux import AS_OF, _dashboard

ENGINE = Path("services/wealth_purification_zakat.py")
PRES = Path("services/wealth_purification_zakat_presentation.py")
UI = Path("components/wealth_purification_zakat_ui.py")
PAGE = Path("pages/10_Wealth.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "alpha_vantage",
    "TwelveData",
    "twelve_data",
    "BorsaIstanbul",
    "fx_rate_refresh",
    "fund_holdings_refresh",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    ".update(",
    "capture_portfolio_snapshot",
    "save_policy",
    "save_planning_fx_schedule",
)
VALUATION_TOKENS = (
    "compute_market_value",
    "WealthPriceService",
    "usdtry",
    "FxRate",
)


def _priced(
    symbol: str,
    *,
    market_value: float,
    weight_pct: float,
    account_id: str = "acc-1",
    account_name: str = "Midas",
    is_cash: bool = False,
    quantity: float = 1.0,
    asset_class: str = "equity",
):
    return _row(
        symbol=symbol,
        price_available=True,
        market_value=market_value,
        currency="USD",
        weight_pct=weight_pct,
        position_id=f"p-{account_id}-{symbol}",
        account_id=account_id,
        asset_id=f"as-{symbol}",
        account_name=account_name,
        quantity=quantity,
        is_cash=is_cash,
        asset_class="cash" if is_cash else asset_class,
    )


def _accounts():
    return [{"id": "acc-1", "name": "Hisse", "institution": "Midas", "currency": "USD"}]


def _assets(*symbols: str):
    return [{"id": f"as-{symbol}", "symbol": symbol} for symbol in symbols]


def _txn(txn_type: str, *, amount: float, symbol: str = "NVDA", account_id: str = "acc-1"):
    return {
        "id": f"{txn_type}-{symbol}-{amount}",
        "account_id": account_id,
        "asset_id": f"as-{symbol}",
        "txn_type": txn_type,
        "amount": amount,
        "currency": "USD",
        "executed_at": "2026-01-15T00:00:00+00:00",
    }


def _complete_view(*, cash: bool = False):
    priced = [
        _priced("NVDA", market_value=80000, weight_pct=80),
        _priced("AAPL", market_value=20000, weight_pct=20),
    ]
    if cash:
        priced.append(
            _priced("CASH", market_value=5000, weight_pct=0, is_cash=True, quantity=5000)
        )
    return _view(priced=priced)


class _Box:
    def __init__(self, parent: "DummySt"):
        self.parent = parent

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def markdown(self, text, **kwargs):
        self.parent.markdowns.append(str(text))

    def write(self, text, **kwargs):
        self.parent.writes.append(str(text))

    def caption(self, text, **kwargs):
        self.parent.captions.append(str(text))

    def metric(self, label, value, **kwargs):
        self.parent.metrics.append(f"{label}: {value}")

    def text_input(self, label, **kwargs):
        return ""


class DummySt:
    def __init__(self, *, basis="Temettü / gelir matrahı", rate=2.5, include_all=False, ratios=None):
        self.basis = basis
        self.rate = rate
        self.include_all = include_all
        self.ratios = ratios or {}
        self.session_state = {}
        self.markdowns: list[str] = []
        self.writes: list[str] = []
        self.captions: list[str] = []
        self.infos: list[str] = []
        self.metrics: list[str] = []

    def markdown(self, text, **kwargs):
        self.markdowns.append(str(text))

    def write(self, text, **kwargs):
        self.writes.append(str(text))

    def caption(self, text, **kwargs):
        self.captions.append(str(text))

    def info(self, text, **kwargs):
        self.infos.append(str(text))

    def radio(self, label, options, **kwargs):
        return self.basis

    def number_input(self, label, **kwargs):
        return self.rate

    def checkbox(self, label, **kwargs):
        return self.include_all

    def text_input(self, label, **kwargs):
        key = str(kwargs.get("key") or "")
        return self.ratios.get(key, "")

    def columns(self, count):
        return [_Box(self) for _ in range(count if isinstance(count, int) else len(count))]

    def expander(self, *args, **kwargs):
        return _Box(self)

    def metric(self, label, value, **kwargs):
        self.metrics.append(f"{label}: {value}")


def _blob(dummy: DummySt) -> str:
    return "\n".join(dummy.markdowns + dummy.writes + dummy.captions + dummy.metrics)


class PurificationCalculationTests(unittest.TestCase):
    def test_missing_ratio_is_not_zero(self) -> None:
        view = _complete_view()
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=True,
            ),
            accounts=_accounts(),
        )
        nvda = next(row for row in result.rows if row.symbol == "NVDA")
        self.assertIsNone(nvda.purification_ratio_pct)
        self.assertIsNone(nvda.purification_amount)
        self.assertNotEqual(nvda.purification_amount, 0.0)
        self.assertIn(MISSING_PURIFICATION_RATIO, nvda.missing_notes)
        self.assertEqual(nvda.status, STATUS_MISSING_INPUT)
        self.assertIsNone(result.estimated_purification)

    def test_explicit_ratio_on_market_value_basis(self) -> None:
        view = _complete_view()
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=True,
                assumptions=(
                    ProductAssumption("p-acc-1-NVDA", purification_ratio_pct=5.0),
                    ProductAssumption("p-acc-1-AAPL", purification_ratio_pct=2.0),
                ),
            ),
            accounts=_accounts(),
        )
        nvda = next(row for row in result.rows if row.symbol == "NVDA")
        aapl = next(row for row in result.rows if row.symbol == "AAPL")
        self.assertAlmostEqual(nvda.purification_amount or 0.0, 4000.0)
        self.assertAlmostEqual(aapl.purification_amount or 0.0, 400.0)
        self.assertAlmostEqual(result.estimated_purification or 0.0, 4400.0)
        self.assertEqual(nvda.basis_value, 80000.0)

    def test_dividend_basis_uses_dividend_only(self) -> None:
        view = _complete_view()
        txns = [
            _txn(TXN_TYPE_DIVIDEND, amount=200.0, symbol="NVDA"),
            _txn(TXN_TYPE_DEPOSIT, amount=5000.0, symbol="NVDA"),
            _txn(TXN_TYPE_DIVIDEND, amount=50.0, symbol="AAPL"),
        ]
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.DIVIDEND_INCOME,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=True,
                assumptions=(
                    ProductAssumption("p-acc-1-NVDA", purification_ratio_pct=10.0),
                    ProductAssumption("p-acc-1-AAPL", purification_ratio_pct=10.0),
                ),
            ),
            accounts=_accounts(),
            assets=_assets("NVDA", "AAPL"),
            transactions=txns,
        )
        nvda = next(row for row in result.rows if row.symbol == "NVDA")
        aapl = next(row for row in result.rows if row.symbol == "AAPL")
        self.assertAlmostEqual(nvda.basis_value or 0.0, 200.0)
        self.assertAlmostEqual(aapl.basis_value or 0.0, 50.0)
        self.assertAlmostEqual(nvda.purification_amount or 0.0, 20.0)
        self.assertAlmostEqual(aapl.purification_amount or 0.0, 5.0)
        self.assertNotIn(5000.0, (nvda.basis_value, aapl.basis_value, result.estimated_purification))


class ZakatAndLimitationTests(unittest.TestCase):
    def test_explicit_zakat_rate(self) -> None:
        view = _complete_view()
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                assumptions=(
                    ProductAssumption("p-acc-1-NVDA", zakat_eligible_pct=100.0),
                    ProductAssumption("p-acc-1-AAPL", zakat_eligible_pct=50.0),
                ),
            ),
            accounts=_accounts(),
        )
        nvda = next(row for row in result.rows if row.symbol == "NVDA")
        aapl = next(row for row in result.rows if row.symbol == "AAPL")
        self.assertAlmostEqual(nvda.zakat_base or 0.0, 80000.0)
        self.assertAlmostEqual(nvda.zakat_amount or 0.0, 2000.0)
        self.assertAlmostEqual(aapl.zakat_base or 0.0, 10000.0)
        self.assertAlmostEqual(aapl.zakat_amount or 0.0, 250.0)
        self.assertAlmostEqual(result.estimated_zakat or 0.0, 2250.0)

    def test_missing_eligibility_not_assumed_100(self) -> None:
        view = _complete_view()
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=False,
                assumptions=(ProductAssumption("p-acc-1-NVDA", purification_ratio_pct=1.0),),
            ),
            accounts=_accounts(),
        )
        for row in result.rows:
            self.assertIsNone(row.zakat_eligible_pct)
            self.assertIsNone(row.zakat_base)
            self.assertIsNone(row.zakat_amount)
            self.assertIn(MISSING_ZAKAT_ELIGIBILITY, row.missing_notes)
        self.assertIsNone(result.estimated_zakat)

    def test_global_100_is_explicit_scenario(self) -> None:
        view = _complete_view()
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=True,
            ),
            accounts=_accounts(),
        )
        self.assertTrue(all(row.zakat_eligible_pct == 100.0 for row in result.rows))
        self.assertAlmostEqual(result.estimated_zakat or 0.0, 2500.0)

    def test_cash_unavailable_limitation(self) -> None:
        view = _complete_view(cash=False)
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
            ),
            accounts=_accounts(),
        )
        self.assertFalse(result.cash_available)
        self.assertIn(CASH_UNAVAILABLE, result.limitations)
        self.assertFalse(any(row.is_cash for row in result.rows))

    def test_partial_valuation_limitation(self) -> None:
        view = _partial_bist_view()
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=True,
            ),
            accounts=[{"id": ACCOUNT, "name": "Broker"}],
        )
        self.assertFalse(result.valuation_complete)
        self.assertIn(PARTIAL_VALUATION_LIMITATION, result.limitations)
        self.assertEqual(result.brief_line, BRIEF_MISSING)

    def test_brief_ready_only_when_inputs_complete(self) -> None:
        view = _complete_view()
        ready = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=True,
                assumptions=(
                    ProductAssumption("p-acc-1-NVDA", purification_ratio_pct=1.0),
                    ProductAssumption("p-acc-1-AAPL", purification_ratio_pct=1.0),
                ),
            ),
            accounts=_accounts(),
        )
        self.assertEqual(ready.brief_line, BRIEF_READY)
        self.assertEqual(ready.missing_input_count, 0)
        empty = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(basis=None, zakat_rate_pct=None),
            accounts=_accounts(),
        )
        self.assertIsNone(empty.brief_line)


class BriefAndUiTests(unittest.TestCase):
    def test_wealth_brief_compact_line(self) -> None:
        view = _complete_view()
        result = calculate_purification_zakat(
            view,
            scenario=PurificationZakatScenario(
                basis=PurificationBasis.MARKET_VALUE,
                zakat_rate_pct=2.5,
                include_all_eligible_at_100=True,
                assumptions=(
                    ProductAssumption("p-acc-1-NVDA", purification_ratio_pct=1.0),
                    ProductAssumption("p-acc-1-AAPL", purification_ratio_pct=1.0),
                ),
            ),
            accounts=_accounts(),
        )
        dashboard = _dashboard(view=view)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=_live_like_decision(),
            purification_zakat=result,
        )
        self.assertIn(BRIEF_READY, brief.today_lines)
        self.assertEqual(sum(1 for line in brief.today_lines if "Arındırma/Zekât" in line), 1)

    def test_disclaimer_and_ui_sections(self) -> None:
        view = _complete_view()
        dummy = DummySt()
        with patch("components.wealth_purification_zakat_ui.st", dummy), patch(
            "components.nabi_design_system._st", return_value=dummy
        ):
            render_purification_zakat_center(
                portfolio_view=view,
                accounts=_accounts(),
                assets=_assets("NVDA", "AAPL"),
            )
        text = _blob(dummy)
        self.assertIn(DISCLAIMER, text)
        self.assertIn("Arındırma & Zekât", text)
        self.assertIn("Özet", text)
        self.assertIn("Varsayımlar", text)
        self.assertIn("Eksik Bilgiler", text)
        self.assertIn("Kullanıcı varsayımıdır", text)

    def test_session_scenario_does_not_invent_ratios(self) -> None:
        scenario = scenario_from_session(
            ["p-acc-1-NVDA"],
            session={
                "wealth_pz_basis": "Güncel piyasa değeri matrahı",
                "wealth_pz_zakat_rate": 2.5,
                "wealth_pz_include_all": False,
                "wealth_pz_ratio_p-acc-1-NVDA": "",
            },
        )
        self.assertIsNone(scenario)

    def test_page_wires_tab(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn("Arındırma & Zekât", page)
        self.assertIn("render_purification_zakat_center", page)

    def test_no_writes_providers_or_duplicate_valuation(self) -> None:
        for path in (ENGINE, PRES, UI):
            source = path.read_text(encoding="utf-8")
            lower = source.lower()
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token.lower(), lower)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
        engine = ENGINE.read_text(encoding="utf-8")
        for token in VALUATION_TOKENS:
            self.assertNotIn(token, engine)
        self.assertIn("dini hüküm veya fetva üretmez", DISCLAIMER)
        self.assertNotIn("fetva", engine.lower().replace("fetva üretmez", ""))


if __name__ == "__main__":
    unittest.main()
