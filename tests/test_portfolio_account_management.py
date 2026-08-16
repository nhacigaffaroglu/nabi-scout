from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from services.portfolio_account_helpers import format_account_display
from services.portfolio_intelligence_contract import PriceQuote
from services.portfolio_intelligence_engine import rollup_portfolio_intelligence, value_position
from services.portfolio_intelligence_enrichment_service import (
    build_portfolio_intelligence_dashboard,
)
from services.portfolio_management_service import PortfolioManagementService
from services.portfolio_research_context import (
    assert_portfolio_research_context_safe,
    build_portfolio_research_context,
)
from services.portfolio_symbol_aggregation import build_consolidated_symbol_rows
from services.wealth_contract import (
    ASSET_CLASS_EQUITY,
    TXN_TYPE_SELL,
    TXN_TYPE_TRANSFER_IN,
    TXN_TYPE_TRANSFER_OUT,
    WealthValidationError,
)


def _position_row(
    *,
    symbol="CRM",
    account_id="acc-midas",
    account_name="Midas — ABD Hisse",
    quantity=10.0,
    average_cost=250.0,
    price=300.0,
    position_id="pos-1",
):
    quote = PriceQuote(price=price, currency="USD", available=True, source="test")
    return value_position(
        position={
            "id": position_id,
            "account_id": account_id,
            "asset_id": f"asset-{symbol}",
            "quantity": quantity,
            "average_cost": average_cost,
            "cost_currency": "USD",
        },
        asset={"symbol": symbol, "asset_class": ASSET_CLASS_EQUITY, "currency": "USD"},
        account={"name": account_name, "institution": account_name.split(" — ")[0]},
        base_currency="USD",
        quote=quote,
    )


class PortfolioAccountHelperTests(unittest.TestCase):
    def test_format_account_display(self) -> None:
        label = format_account_display(
            {"institution": "Midas", "name": "ABD Hisse", "id": "1"}
        )
        self.assertEqual(label, "Midas — ABD Hisse")


class ConsolidatedExposureTests(unittest.TestCase):
    def _dashboard(self, rows):
        base = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=rows,
            price_provider="test",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        accounts_by_id = {
            "acc-midas": {"id": "acc-midas", "institution": "Midas", "name": "ABD Hisse"},
            "acc-ykb": {"id": "acc-ykb", "institution": "YKB", "name": "Yatırım"},
        }
        return build_portfolio_intelligence_dashboard(
            base,
            accounts_by_id=accounts_by_id,
        )

    def test_same_symbol_two_accounts(self) -> None:
        rows = [
            _position_row(account_id="acc-midas", account_name="Midas — ABD Hisse", quantity=10),
            _position_row(
                account_id="acc-ykb",
                account_name="YKB — Yatırım",
                quantity=5,
                average_cost=220.0,
                position_id="pos-2",
            ),
        ]
        dashboard = self._dashboard(rows)
        self.assertEqual(len(dashboard.enriched_positions), 2)
        self.assertEqual(len(dashboard.consolidated_symbols), 1)
        consolidated = dashboard.consolidated_symbols[0]
        self.assertEqual(consolidated.symbol, "CRM")
        self.assertAlmostEqual(consolidated.total_quantity, 15.0)
        self.assertEqual(len(consolidated.account_breakdown), 2)

    def test_institution_allocation(self) -> None:
        rows = [
            _position_row(account_id="acc-midas", quantity=10, price=300),
            _position_row(
                account_id="acc-ykb",
                quantity=5,
                price=200,
                position_id="pos-2",
            ),
        ]
        dashboard = self._dashboard(rows)
        self.assertEqual(len(dashboard.account_allocation), 2)
        weight_sum = sum(slice_row.weight_pct for slice_row in dashboard.account_allocation)
        self.assertAlmostEqual(weight_sum, 100.0)


class PortfolioManagementServiceTests(unittest.TestCase):
    def test_add_holding_requires_account(self) -> None:
        wealth = MagicMock()
        wealth.user_id = "u1"
        service = PortfolioManagementService(wealth)
        with self.assertRaises(WealthValidationError):
            service.add_holding(
                account_id="",
                symbol="CRM",
                quantity=1,
                average_cost=10,
            )

    def test_transfer_uses_explicit_transfer_types(self) -> None:
        wealth = MagicMock()
        wealth.user_id = "u1"
        wealth.list_positions.return_value = [
            {
                "account_id": "acc-midas",
                "asset_id": "asset-crm",
                "quantity": 10.0,
                "average_cost": 250.0,
                "cost_currency": "USD",
            }
        ]
        wealth.assets.get_by_id.return_value = {
            "id": "asset-crm",
            "symbol": "CRM",
            "currency": "USD",
            "asset_class": ASSET_CLASS_EQUITY,
            "market": "US",
        }
        wealth.post_transfer.return_value = {"id": "txn-in", "txn_type": TXN_TYPE_TRANSFER_IN}
        service = PortfolioManagementService(wealth)
        service.transfer_holding(
            from_account_id="acc-midas",
            to_account_id="acc-ykb",
            asset_id="asset-crm",
            quantity=5.0,
        )
        wealth.post_transfer.assert_called_once()
        call = wealth.post_transfer.call_args.kwargs
        self.assertEqual(call["from_account_id"], "acc-midas")
        self.assertEqual(call["to_account_id"], "acc-ykb")
        self.assertAlmostEqual(call["quantity"], 5.0)
        self.assertAlmostEqual(call["price"], 250.0)
        wealth.post_transaction.assert_not_called()

    def test_close_posts_full_sell(self) -> None:
        wealth = MagicMock()
        wealth.user_id = "u1"
        wealth.list_positions.return_value = [
            {
                "account_id": "acc-midas",
                "asset_id": "asset-crm",
                "quantity": 3.0,
                "average_cost": 100.0,
                "cost_currency": "USD",
            }
        ]
        wealth.assets.get_by_id.return_value = {"currency": "USD"}
        service = PortfolioManagementService(wealth)
        service.close_holding(account_id="acc-midas", asset_id="asset-crm")
        wealth.post_transaction.assert_called_once()
        self.assertEqual(wealth.post_transaction.call_args.kwargs["txn_type"], TXN_TYPE_SELL)
        self.assertAlmostEqual(
            wealth.post_transaction.call_args.kwargs["quantity"],
            3.0,
        )


class PortfolioResearchContextAccountTests(unittest.TestCase):
    def test_context_includes_accounts(self) -> None:
        rows = [
            _position_row(account_id="acc-midas", quantity=10),
            _position_row(
                account_id="acc-ykb",
                quantity=5,
                position_id="pos-2",
            ),
        ]
        base = rollup_portfolio_intelligence(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            rows=rows,
            price_provider="test",
            unique_price_symbols_fetched=0,
            valuation_errors=[],
        )
        dashboard = build_portfolio_intelligence_dashboard(
            base,
            accounts_by_id={
                "acc-midas": {"institution": "Midas", "name": "ABD Hisse"},
                "acc-ykb": {"institution": "YKB", "name": "Yatırım"},
            },
        )
        context = build_portfolio_research_context(dashboard)
        payload = context.to_dict()
        assert_portfolio_research_context_safe(payload)
        self.assertEqual(context.schema_version, "portfolio_research_context_v2")
        self.assertEqual(len(context.consolidated_positions), 1)
        self.assertGreaterEqual(len(context.accounts), 1)
        serialized = json.dumps(payload)
        self.assertNotIn("password", serialized.lower())


if __name__ == "__main__":
    unittest.main()
