from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from components.wealth_institution_center_ui import render_institution_center
from services.portfolio_intelligence_contract import PositionValuationRow
from services.wealth_brief_presentation import build_wealth_brief
from services.wealth_institution_center_presentation import (
    BRIEF_TEMPLATE,
    CASH_UNAVAILABLE,
    INCOMPLETE_LIMITATION,
    MULTI_INSTITUTION_TITLE,
    SECTION_TITLE,
    present_institution_center,
)
from tests.test_portfolio_decision_center_ui import ACCOUNT, _live_like_decision
from tests.test_portfolio_decision_intelligence import _partial_bist_view, _row, _view
from tests.test_wealth_brief_ux import AS_OF, _dashboard

PRES = Path("services/wealth_institution_center_presentation.py")
UI = Path("components/wealth_institution_center_ui.py")
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
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "BorsaIstanbul",
    "borsaistanbul",
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
    "create_account",
    "create_institution_account",
)


def _priced(
    symbol: str,
    *,
    account_id: str,
    account_name: str,
    market_value: float,
    weight_pct: float,
    quantity: float = 1.0,
    is_cash: bool = False,
    asset_class: str = "equity",
) -> PositionValuationRow:
    return _row(
        symbol=symbol,
        price_available=True,
        market_value=market_value,
        currency="USD",
        weight_pct=weight_pct,
        position_id=f"p-{account_id}-{symbol}",
        account_id=account_id,
        asset_id=f"as-{account_id}-{symbol}",
        account_name=account_name,
        quantity=quantity,
        is_cash=is_cash,
        asset_class="cash" if is_cash else asset_class,
    )


def _accounts(*rows: dict) -> list[dict]:
    return list(rows)


def _two_institution_view(*, cash: bool = False):
    priced = [
        _priced("NVDA", account_id="acc-midas", account_name="Midas Hisse", market_value=60000, weight_pct=60, quantity=10),
        _priced("AAPL", account_id="acc-ibkr", account_name="IBKR", market_value=40000, weight_pct=40, quantity=20),
    ]
    if cash:
        priced.append(
            _priced(
                "CASH",
                account_id="acc-midas",
                account_name="Midas Hisse",
                market_value=5000,
                weight_pct=0,
                quantity=5000,
                is_cash=True,
            )
        )
    view = _view(priced=priced)
    accounts = _accounts(
        {"id": "acc-midas", "name": "Hisse", "institution": "Midas", "currency": "USD"},
        {"id": "acc-ibkr", "name": "Broker", "institution": "IBKR", "currency": "USD"},
    )
    return view, accounts


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


class DummySt:
    def __init__(self):
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

    def warning(self, text, **kwargs):
        self.infos.append(str(text))

    def columns(self, count):
        size = count if isinstance(count, int) else len(count)
        return [_Box(self) for _ in range(size)]

    def expander(self, *args, **kwargs):
        return _Box(self)

    def metric(self, label, value, **kwargs):
        self.metrics.append(f"{label}: {value}")


def _blob(dummy: DummySt) -> str:
    return "\n".join(
        dummy.markdowns + dummy.writes + dummy.captions + dummy.infos + dummy.metrics
    )


class InstitutionGroupingTests(unittest.TestCase):
    def test_groups_by_institution_field(self) -> None:
        view, accounts = _two_institution_view()
        center = present_institution_center(view, accounts)
        names = [row.name for row in center.institutions]
        self.assertEqual(names, ["Midas", "IBKR"])
        midas = center.institutions[0]
        self.assertEqual(midas.account_id, "acc-midas")
        self.assertEqual(midas.symbols, ("NVDA",))
        self.assertEqual(midas.holdings_count, 1)
        self.assertAlmostEqual(midas.total_value, 60000.0)
        self.assertAlmostEqual(midas.securities_market_value, 60000.0)
        self.assertAlmostEqual(midas.portfolio_share_pct, 60.0)

    def test_falls_back_to_account_identity_without_institution(self) -> None:
        view = _view(
            priced=[
                _priced("NVDA", account_id="acc-1", account_name="Hesap A", market_value=70, weight_pct=70),
                _priced("AAPL", account_id="acc-2", account_name="Hesap B", market_value=30, weight_pct=30),
            ]
        )
        accounts = _accounts(
            {"id": "acc-1", "name": "Hesap A", "currency": "USD"},
            {"id": "acc-2", "name": "Hesap B", "currency": "USD"},
        )
        center = present_institution_center(view, accounts)
        names = {row.name for row in center.institutions}
        self.assertEqual(names, {"Hesap A", "Hesap B"})
        self.assertEqual({row.account_id for row in center.institutions}, {"acc-1", "acc-2"})

    def test_same_institution_rolls_up_accounts(self) -> None:
        view = _view(
            priced=[
                _priced("NVDA", account_id="a1", account_name="Midas 1", market_value=40, weight_pct=40),
                _priced("AAPL", account_id="a2", account_name="Midas 2", market_value=60, weight_pct=60),
            ]
        )
        accounts = _accounts(
            {"id": "a1", "name": "Hisse", "institution": "Midas", "currency": "USD"},
            {"id": "a2", "name": "Fon", "institution": "Midas", "currency": "USD"},
        )
        center = present_institution_center(view, accounts)
        self.assertEqual(len(center.institutions), 1)
        card = center.institutions[0]
        self.assertEqual(card.name, "Midas")
        self.assertEqual(set(card.account_ids), {"a1", "a2"})
        self.assertAlmostEqual(card.total_value, 100.0)
        self.assertEqual(set(card.symbols), {"NVDA", "AAPL"})


class InstitutionTotalTests(unittest.TestCase):
    def test_totals_reconcile_without_duplicate_market_value(self) -> None:
        view, accounts = _two_institution_view()
        center = present_institution_center(view, accounts)
        self.assertAlmostEqual(
            sum(row.total_value for row in center.institutions),
            view.priced_total_market_value,
        )
        self.assertAlmostEqual(center.totals.total_value, view.priced_total_market_value)
        self.assertAlmostEqual(
            sum(row.securities_market_value for row in center.institutions),
            center.totals.securities_market_value,
        )
        self.assertEqual(len(view.priced_positions), 2)

    def test_holdings_use_canonical_row_values(self) -> None:
        view, accounts = _two_institution_view()
        center = present_institution_center(view, accounts)
        nvda = center.institutions[0].holdings[0]
        self.assertEqual(nvda.symbol, "NVDA")
        self.assertEqual(nvda.quantity, 10)
        self.assertAlmostEqual(nvda.market_value or 0.0, 60000.0)
        self.assertAlmostEqual(nvda.portfolio_weight_pct or 0.0, 60.0)
        self.assertEqual(nvda.asset_type, "equity")


class CashAndShareTests(unittest.TestCase):
    def test_cash_unavailable_when_no_cash_row(self) -> None:
        view, accounts = _two_institution_view(cash=False)
        center = present_institution_center(view, accounts)
        self.assertFalse(center.totals.cash_available)
        self.assertIsNone(center.totals.cash_value)
        for card in center.institutions:
            self.assertFalse(card.cash_available)
            self.assertIsNone(card.cash_value)

    def test_cash_uses_canonical_cash_row(self) -> None:
        view, accounts = _two_institution_view(cash=True)
        center = present_institution_center(view, accounts)
        midas = next(row for row in center.institutions if row.name == "Midas")
        ibkr = next(row for row in center.institutions if row.name == "IBKR")
        self.assertTrue(midas.cash_available)
        self.assertAlmostEqual(midas.cash_value or 0.0, 5000.0)
        self.assertAlmostEqual(midas.securities_market_value, 60000.0)
        self.assertAlmostEqual(midas.total_value, 65000.0)
        self.assertFalse(ibkr.cash_available)
        self.assertIsNone(ibkr.cash_value)
        self.assertTrue(center.totals.cash_available)
        self.assertAlmostEqual(center.totals.cash_value or 0.0, 5000.0)
        self.assertAlmostEqual(sum(row.total_value for row in center.institutions), view.priced_total_market_value)

    def test_portfolio_share_from_canonical_total(self) -> None:
        view, accounts = _two_institution_view()
        center = present_institution_center(view, accounts)
        shares = {row.name: row.portfolio_share_pct for row in center.institutions}
        self.assertAlmostEqual(shares["Midas"], 60.0)
        self.assertAlmostEqual(shares["IBKR"], 40.0)
        self.assertAlmostEqual(sum(shares.values()), 100.0)


class ConcentrationAndOverlapTests(unittest.TestCase):
    def test_concentration_is_top_share_only(self) -> None:
        view, accounts = _two_institution_view()
        center = present_institution_center(view, accounts)
        self.assertEqual(center.concentration.top_name, "Midas")
        self.assertAlmostEqual(center.concentration.top_share_pct or 0.0, 60.0)
        source = PRES.read_text(encoding="utf-8")
        self.assertNotIn("INSTITUTION_CONCENTRATION_THRESHOLD", source)
        self.assertNotIn("alert", source.lower())

    def test_multi_account_same_symbol(self) -> None:
        view = _view(
            priced=[
                _priced("AAPL", account_id="acc-midas", account_name="Midas", market_value=30, weight_pct=30, quantity=2),
                _priced("AAPL", account_id="acc-ibkr", account_name="IBKR", market_value=70, weight_pct=70, quantity=5),
            ]
        )
        accounts = _accounts(
            {"id": "acc-midas", "name": "Hisse", "institution": "Midas", "currency": "USD"},
            {"id": "acc-ibkr", "name": "Broker", "institution": "IBKR", "currency": "USD"},
        )
        center = present_institution_center(view, accounts)
        self.assertEqual(len(center.multi_institution_holdings), 1)
        row = center.multi_institution_holdings[0]
        self.assertEqual(row.symbol, "AAPL")
        self.assertEqual(set(row.institutions), {"Midas", "IBKR"})
        self.assertAlmostEqual(row.total_quantity, 7.0)
        by_account = dict(row.quantities_by_account)
        self.assertAlmostEqual(by_account["Midas"], 2.0)
        self.assertAlmostEqual(by_account["IBKR"], 5.0)

    def test_single_institution_symbol_not_listed_as_multi(self) -> None:
        view, accounts = _two_institution_view()
        center = present_institution_center(view, accounts)
        self.assertEqual(center.multi_institution_holdings, ())


class IncompleteAndBriefTests(unittest.TestCase):
    def test_incomplete_valuation_limitation(self) -> None:
        view = _partial_bist_view()
        center = present_institution_center(view, [{"id": ACCOUNT, "name": "Broker"}])
        self.assertFalse(center.valuation_complete)
        self.assertEqual(center.limitation, INCOMPLETE_LIMITATION)
        self.assertIsNone(center.brief_line)

    def test_complete_view_brief_line(self) -> None:
        view, accounts = _two_institution_view()
        center = present_institution_center(view, accounts)
        self.assertTrue(center.valuation_complete)
        self.assertEqual(
            center.brief_line,
            BRIEF_TEMPLATE.format(name="Midas", share=60.0),
        )

    def test_wealth_brief_includes_reliable_institution_line(self) -> None:
        view, accounts = _two_institution_view()
        center = present_institution_center(view, accounts)
        dashboard = _dashboard(view=view)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=_live_like_decision(),
            institution_center=center,
        )
        self.assertIn(center.brief_line, brief.today_lines)

    def test_wealth_brief_omits_institution_line_when_incomplete(self) -> None:
        view = _partial_bist_view()
        center = present_institution_center(view, [{"id": ACCOUNT, "name": "Broker"}])
        dashboard = _dashboard(view=view)
        brief = build_wealth_brief(
            as_of_date=AS_OF,
            portfolio_view=view,
            dashboard=dashboard,
            decision=_live_like_decision(),
            institution_center=center,
        )
        self.assertFalse(brief.header.valuation_complete)
        self.assertTrue(all("Kurum dağılımı" not in line for line in brief.today_lines))


class RenderAndSafetyTests(unittest.TestCase):
    def test_ui_renders_required_sections(self) -> None:
        view, accounts = _two_institution_view(cash=False)
        dummy = DummySt()
        with patch("components.wealth_institution_center_ui.st", dummy), patch(
            "components.nabi_design_system._st", return_value=dummy
        ):
            render_institution_center(portfolio_view=view, accounts=accounts)
        text = _blob(dummy)
        self.assertIn(SECTION_TITLE, text)
        self.assertIn("Midas", text)
        self.assertIn("IBKR", text)
        self.assertIn(CASH_UNAVAILABLE, text)
        self.assertIn(MULTI_INSTITUTION_TITLE, text)
        self.assertIn("Kurum yoğunlaşması", text)

    def test_page_wires_tab_without_standalone_app(self) -> None:
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn("Kurum Merkezi", page)
        self.assertIn("render_institution_center", page)
        self.assertIn("present_institution_center", Path("components/wealth_brief_ui.py").read_text(encoding="utf-8"))

    def test_no_writes_or_providers(self) -> None:
        for path in (PRES, UI):
            source = path.read_text(encoding="utf-8")
            lower = source.lower()
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token.lower(), lower)
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
        self.assertNotIn("WealthPriceService", PRES.read_text(encoding="utf-8"))
        self.assertNotIn("compute_market_value", PRES.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
