from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from repositories.wealth_portfolio_admin_repository import WealthPortfolioAdminRepository


class Wave4MonitorWiringTests(unittest.TestCase):
    def test_monitor_service_has_wave4_refresh(self) -> None:
        source = Path("services/monitor_intelligence_service.py").read_text(encoding="utf-8")
        self.assertIn("_refresh_wave4_events", source)
        self.assertIn("detect_fx_stale_events", source)

    def test_allocation_change_detection(self) -> None:
        from services.wave4_monitor_context import allocation_changed

        prev = {"asset_class_allocation": [{"label": "equity", "weight_pct": 50.0}]}
        curr = {"asset_class_allocation": [{"label": "equity", "weight_pct": 52.0}]}
        self.assertTrue(allocation_changed(prev, curr, allocation_key="asset_class_allocation"))


class PositionFilterTests(unittest.TestCase):
    def test_position_table_supports_asset_and_currency_filters(self) -> None:
        source = Path("components/portfolio_intelligence_ui.py").read_text(encoding="utf-8")
        self.assertIn("asset_type_filter", source)
        self.assertIn("currency_filter", source)


class MultiUserSnapshotDiscoveryTests(unittest.TestCase):
    def test_admin_repository_lists_portfolios_with_accounts(self) -> None:
        client = MagicMock()
        client.table.return_value.select.return_value.limit.return_value.execute.return_value.data = [
            {"id": "pf-1", "user_id": "u1", "name": "Main", "base_currency": "USD", "is_default": True}
        ]
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "acc-1"}
        ]
        repo = WealthPortfolioAdminRepository(client)
        rows = repo.list_active_portfolios_for_snapshot()
        self.assertEqual(len(rows), 1)


class FxAttributionTests(unittest.TestCase):
    def test_unavailable_without_history(self) -> None:
        from services.fx_attribution_service import FX_ATTRIBUTION_UNAVAILABLE, build_fx_attribution_view

        view = build_fx_attribution_view(symbol="SAP", native_currency="EUR", base_currency="USD")
        self.assertEqual(view.status, FX_ATTRIBUTION_UNAVAILABLE)


class ManualEntryTests(unittest.TestCase):
    def test_add_holding_accepts_display_name(self) -> None:
        source = Path("services/portfolio_management_service.py").read_text(encoding="utf-8")
        self.assertIn("name: Optional[str] = None", source)
        ui = Path("components/portfolio_management_ui.py").read_text(encoding="utf-8")
        self.assertIn("Görünen ad", ui)
        self.assertIn("Not (opsiyonel)", ui)


if __name__ == "__main__":
    unittest.main()
