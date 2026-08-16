import unittest
from unittest.mock import MagicMock

from services.data_quality_center_service import build_data_quality_summary
from services.system_health_service import SystemHealthService, JOB_LABELS


class _DashboardStub:
    class _Base:
        unpriced_position_count = 2
        foreign_currency_position_count = 1
        fx_supported = False

    base = _Base()
    participation_unknown_weight_pct = 25.0
    unresearched_weight_pct = 30.0


class DataQualityCenterTests(unittest.TestCase):
    def test_builds_issues_from_dashboard(self) -> None:
        summary = build_data_quality_summary(_DashboardStub(), fx_stale=True, fund_holdings_stale=True)
        codes = {issue.code for issue in summary.issues}
        self.assertIn("missing_prices", codes)
        self.assertIn("missing_fx", codes)
        self.assertIn("stale_fx", codes)
        self.assertIn("stale_fund_holdings", codes)
        self.assertTrue(summary.partial_valuation)


class SystemHealthServiceTests(unittest.TestCase):
    def test_lists_all_job_labels(self) -> None:
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        select = MagicMock()
        table.select.return_value = select
        select.eq.return_value = select
        select.order.return_value = select
        select.limit.return_value = select
        select.execute.return_value = MagicMock(data=[])
        rows = SystemHealthService(client).list_automation_health()
        self.assertEqual(len(rows), len(JOB_LABELS))
