from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from components.portfolio_economic_exposure_ui import load_persisted_fund_snapshots
from services.fmp_client import FMPError
from services.fund_holdings_refresh_service import (
    LOOKTHROUGH_ONBOARDING_SYMBOLS,
    FundHoldingsRefreshService,
    normalize_provider_asset_type,
)
from services.fund_holdings_service import FundHoldingsService
from services.portfolio_economic_exposure import classify_instrument_exposure
from tests.test_portfolio_economic_exposure import _etf


REFRESH = Path("services/fund_holdings_refresh_service.py")
SCRIPT = Path("scripts/refresh_etf_lookthrough_evidence.py")
ENGINE = Path("services/portfolio_economic_exposure.py")
UI = Path("components/portfolio_economic_exposure_ui.py")
PI = Path("pages/11_Portfolio_Intelligence.py")


class FakeFundRepo:
    def __init__(self) -> None:
        self.snapshots: Dict[tuple, Dict[str, Any]] = {}
        self.holdings: Dict[str, List[Dict[str, Any]]] = {}
        self._ids = 0

    def upsert_snapshot(self, **payload) -> Dict[str, Any]:
        key = (
            str(payload["fund_symbol"]).upper(),
            payload["as_of"].isoformat() if hasattr(payload["as_of"], "isoformat") else str(payload["as_of"]),
            payload["source"],
        )
        existing = self.snapshots.get(key)
        if existing is None:
            self._ids += 1
            row = {"id": f"snap-{self._ids}", **payload, "as_of": key[1], "fund_symbol": key[0]}
            self.snapshots[key] = row
            return row
        existing.update({"coverage_pct": payload.get("coverage_pct"), "underlying_count": payload.get("underlying_count")})
        return existing

    def replace_holdings(self, snapshot_id: str, holdings: List[Dict[str, Any]]) -> int:
        self.holdings[snapshot_id] = list(holdings)
        return len(holdings)

    def get_latest_snapshot(self, fund_symbol: str) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.snapshots.values() if row["fund_symbol"] == fund_symbol.upper()]
        if not rows:
            return None
        return sorted(rows, key=lambda item: item["as_of"], reverse=True)[0]

    def list_holdings(self, snapshot_id: str) -> List[Dict[str, Any]]:
        return list(self.holdings.get(snapshot_id, []))

    def get_snapshot_for_date(self, **kwargs):
        return None


def _service(fmp=None) -> FundHoldingsRefreshService:
    service = FundHoldingsRefreshService(client=object(), fmp_client=fmp)
    service.repo = FakeFundRepo()
    service.runs = MagicMock()
    return service


class ProviderTypeNormalizationTests(unittest.TestCase):
    def test_maps_explicit_types_only(self) -> None:
        self.assertEqual(normalize_provider_asset_type("Equity"), "equity")
        self.assertEqual(normalize_provider_asset_type("SUKUK"), "sukuk")
        self.assertEqual(normalize_provider_asset_type("Bond"), "fixed_income")
        self.assertEqual(normalize_provider_asset_type("REIT"), "real_estate")
        self.assertEqual(normalize_provider_asset_type("Cash"), "cash")
        self.assertIsNone(normalize_provider_asset_type(None))
        self.assertIsNone(normalize_provider_asset_type("other"))
        self.assertIsNone(normalize_provider_asset_type("SP Funds Sukuk ETF"))


class RefreshPersistenceTests(unittest.TestCase):
    def test_persists_weighted_holdings_and_does_not_default_equity(self) -> None:
        fmp = MagicMock()
        fmp.etf_holdings.return_value = [
            {"asset": "AAPL", "name": "Apple", "weightPercentage": 90.0, "assetType": "Equity"},
            {"asset": "CASH", "name": "Cash", "weightPercentage": 5.0, "assetType": "Cash"},
            {"asset": "XYZ", "name": "Mystery", "weightPercentage": 5.0},
        ]
        service = _service(fmp)
        results = service.refresh_requested_symbols(["SPUS"], as_of=date(2026, 8, 18))
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["persisted"])
        self.assertTrue(results[0]["supported"])
        self.assertEqual(results[0]["holdings_count"], 3)
        self.assertAlmostEqual(results[0]["coverage_pct"], 100.0)
        snap = next(iter(service.repo.snapshots.values()))
        rows = service.repo.holdings[snap["id"]]
        types = {row["underlying_symbol"]: row["asset_type"] for row in rows}
        self.assertEqual(types["AAPL"], "equity")
        self.assertEqual(types["CASH"], "cash")
        self.assertIsNone(types["XYZ"])
        self.assertNotIn("or \"equity\"", REFRESH.read_text(encoding="utf-8"))

    def test_empty_provider_payload_does_not_persist(self) -> None:
        fmp = MagicMock()
        fmp.etf_holdings.return_value = []
        service = _service(fmp)
        results = service.refresh_requested_symbols(["SPSK"])
        self.assertFalse(results[0]["persisted"])
        self.assertFalse(results[0]["supported"])
        self.assertEqual(service.repo.snapshots, {})

    def test_plan_restricted_does_not_persist(self) -> None:
        fmp = MagicMock()
        fmp.etf_holdings.side_effect = FMPError("denied", error_class="plan_restricted", endpoint="etf/holdings")
        service = _service(fmp)
        results = service.refresh_requested_symbols(["SPRE"])
        self.assertFalse(results[0]["persisted"])
        self.assertEqual(results[0]["error_class"], "plan_restricted")
        self.assertEqual(service.repo.snapshots, {})

    def test_duplicate_refresh_is_idempotent_for_same_day(self) -> None:
        fmp = MagicMock()
        fmp.etf_holdings.return_value = [
            {"asset": "AAPL", "name": "Apple", "weightPercentage": 100.0, "assetType": "Equity"},
        ]
        service = _service(fmp)
        first = service.refresh_requested_symbols(["SPUS"], as_of=date(2026, 8, 18))
        second = service.refresh_requested_symbols(["SPUS"], as_of=date(2026, 8, 18))
        self.assertTrue(first[0]["persisted"])
        self.assertTrue(second[0]["persisted"])
        self.assertEqual(len(service.repo.snapshots), 1)
        snap_id = next(iter(service.repo.snapshots.values()))["id"]
        self.assertEqual(len(service.repo.holdings[snap_id]), 1)

    def test_latest_snapshot_is_deterministic(self) -> None:
        reader = FundHoldingsService(client=object())
        repo = FakeFundRepo()
        older = repo.upsert_snapshot(
            fund_symbol="SPWO",
            fund_type="etf",
            as_of=date(2026, 8, 1),
            source="fmp_etf_holdings",
            coverage_pct=10,
            underlying_count=1,
        )
        newer = repo.upsert_snapshot(
            fund_symbol="SPWO",
            fund_type="etf",
            as_of=date(2026, 8, 18),
            source="fmp_etf_holdings",
            coverage_pct=90,
            underlying_count=2,
        )
        repo.replace_holdings(older["id"], [{"weight_pct": 10, "asset_type": "equity", "underlying_symbol": "OLD"}])
        repo.replace_holdings(newer["id"], [{"weight_pct": 90, "asset_type": "equity", "underlying_symbol": "NEW"}])
        reader.repo = repo
        snapshot = reader.get_snapshot("SPWO")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.as_of, "2026-08-18")
        self.assertEqual(snapshot.holdings[0].underlying_symbol, "NEW")

    def test_controlled_refresh_calls_only_requested_symbols(self) -> None:
        fmp = MagicMock()
        fmp.etf_holdings.return_value = [
            {"asset": "AAPL", "weightPercentage": 100.0, "assetType": "Equity"},
        ]
        service = _service(fmp)
        service.refresh_requested_symbols(["SPUS", "SPSK"])
        called = [call.args[0] for call in fmp.etf_holdings.call_args_list]
        self.assertEqual(called, ["SPUS", "SPSK"])
        self.assertEqual(service.provider_calls, 2)
        self.assertNotIn("HLAL", called)

    def test_persisted_snapshot_is_consumed_by_exposure_engine(self) -> None:
        fmp = MagicMock()
        fmp.etf_holdings.return_value = [
            {"asset": "AAPL", "name": "Apple", "weightPercentage": 70.0, "assetType": "Equity"},
            {"asset": "CASH", "name": "Cash", "weightPercentage": 30.0, "assetType": "Cash"},
        ]
        service = _service(fmp)
        service.refresh_requested_symbols(["SPUS"], as_of=date(2026, 8, 18))
        reader = FundHoldingsService(client=object())
        reader.repo = service.repo
        snapshot = reader.get_snapshot("SPUS")
        view = classify_instrument_exposure(_etf("SPUS"), fund_snapshots={"SPUS": snapshot})
        buckets = {row.exposure_bucket: row.weight_pct for row in view.economic_exposures}
        self.assertAlmostEqual(buckets["equity"], 70.0)
        self.assertAlmostEqual(buckets["cash"], 30.0)
        self.assertEqual(view.economic_exposures[0].evidence_source.value, "PERSISTED_HOLDINGS_LOOKTHROUGH")

    def test_no_snapshot_remains_unknown(self) -> None:
        view = classify_instrument_exposure(_etf("SPWO"), fund_snapshots={})
        self.assertEqual(view.economic_exposures[0].exposure_bucket, "unknown")


class SafetyTests(unittest.TestCase):
    def test_script_allowlist_is_only_the_four_etfs(self) -> None:
        self.assertEqual(LOOKTHROUGH_ONBOARDING_SYMBOLS, ("SPUS", "SPSK", "SPRE", "SPWO"))
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("LOOKTHROUGH_ONBOARDING_SYMBOLS", source)
        self.assertNotIn("discover_fund_symbols_for_refresh", source)
        self.assertNotIn("openai", source.lower())
        self.assertNotIn("SECFinancialClient", source)

    def test_refresh_does_not_write_ledger_policy_or_overrides(self) -> None:
        source = REFRESH.read_text(encoding="utf-8")
        for token in (
            "portfolio_allocation_policies",
            "post_transaction",
            "wealth_ledger",
            "exposure_override",
            "user_confirmed",
        ):
            self.assertNotIn(token, source)
        self.assertNotIn("SPUS = equity", source)
        self.assertNotIn("SPSK = sukuk", source)

    def test_no_ticker_name_guessing_in_refresh(self) -> None:
        source = REFRESH.read_text(encoding="utf-8")
        self.assertNotIn("contains REIT", source)
        self.assertNotIn("therefore sukuk", source)
        self.assertNotIn("S&P 500", source)
        self.assertNotIn("or \"equity\"", source)
        self.assertNotIn("or 'equity'", source)

    def test_pi_render_does_not_call_fund_refresh(self) -> None:
        for path in (ENGINE, UI, PI):
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("refresh_requested_symbols", raw)
            self.assertNotIn("FundHoldingsRefreshService", raw)
        wealth = MagicMock()
        wealth.client = object()
        with patch(
            "services.fund_holdings_service.FundHoldingsService.get_snapshot",
            return_value=None,
        ) as get_snapshot, patch(
            "services.fund_holdings_refresh_service.FundHoldingsRefreshService"
        ) as refresh:
            load_persisted_fund_snapshots(wealth, LOOKTHROUGH_ONBOARDING_SYMBOLS)
            self.assertEqual(get_snapshot.call_count, 4)
            refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
