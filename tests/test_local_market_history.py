from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.local_market_history_service import (
    PriceObservation,
    compute_local_momentum,
    observations_from_wealth_rows,
)
from services.nabi_score_v4 import calculate_nabi_score_v4
from services.security_facts_service import SecurityFactsService


def _obs(days_ago: int, price: float) -> PriceObservation:
    now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    return PriceObservation(as_of=now - timedelta(days=days_ago), price=price)


class MomentumSufficiencyTests(unittest.TestCase):
    def test_identical_stale_marks_are_insufficient(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        rows = [
            {
                "captured_at": (now - timedelta(days=offset)).isoformat(),
                "valuation_payload": {
                    "priced_positions": [{"symbol": "AAPL", "price": 309.35}]
                },
            }
            for offset in range(7)
        ]
        series = observations_from_wealth_rows(rows, "AAPL")
        facts = compute_local_momentum(series)
        self.assertEqual(facts.unique_prices, 1)
        self.assertFalse(facts.usable)
        self.assertIsNone(facts.values["return_1d"])
        self.assertIsNone(facts.values["return_1y"])
        self.assertIsNone(facts.values["volatility"])

    def test_one_week_crm_like_series_fills_short_horizons_only(self) -> None:
        series = (
            _obs(7, 209.17),
            _obs(5, 209.06),
            _obs(3, 205.69),
            _obs(2, 249.26),
            _obs(1, 260.74),
            _obs(0, 256.0),
        )
        facts = compute_local_momentum(series)
        self.assertTrue(facts.usable)
        self.assertIsNotNone(facts.values["return_1d"])
        self.assertIsNotNone(facts.values["return_1w"])
        self.assertIsNone(facts.values["return_1m"])
        self.assertIsNone(facts.values["return_3m"])
        self.assertIsNone(facts.values["return_6m"])
        self.assertIsNone(facts.values["return_1y"])
        self.assertIsNone(facts.values["high_52w"])
        self.assertIsNone(facts.values["drawdown"])
        self.assertIsNone(facts.values["volatility"])
        self.assertTrue(all(item.source == "wealth_portfolio_snapshots" for item in facts.provenance))

    def test_single_price_is_not_history(self) -> None:
        facts = compute_local_momentum((_obs(0, 100.0),))
        self.assertFalse(facts.usable)
        self.assertIsNone(facts.values["return_1d"])

    def test_facts_service_ingests_local_momentum(self) -> None:
        momentum = compute_local_momentum((_obs(7, 200.0), _obs(0, 220.0)))
        facts = SecurityFactsService().build(
            "CRM",
            local_momentum=momentum,
            allow_sec_cache_replay=False,
        )
        self.assertIsNotNone(facts.return_1w)
        self.assertIsNone(facts.return_1y)

    def test_no_paid_provider_and_hybrid_off(self) -> None:
        source = Path("services/local_market_history_service.py").read_text(encoding="utf-8")
        self.assertNotIn("historical_price_eod_light", source)
        self.assertNotIn("FMPClient", source)
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        v4 = calculate_nabi_score_v4(
            revenue_growth_1y=12,
            revenue_cagr_3y=14,
            eps_growth_1y=15,
            eps_cagr_3y=16,
            fcf_cagr_3y=11,
            gross_margin=50,
            operating_margin=22,
            net_margin=18,
            fcf_margin=15,
            roic=20,
            roe=22,
            roa=10,
            current_ratio=1.8,
            debt_to_equity=0.4,
            net_debt_to_fcf=1.0,
            interest_coverage=12,
            pe_ratio=16,
            price_to_sales=3,
            price_to_book=3,
            share_change_3y=None,
            payout_ratio=None,
            market_cap=80_000_000_000,
            average_volume=None,
            portfolio_fit=80,
            participation_score=100,
            participation_status="Uygun",
            completeness=90,
        )
        self.assertIn("nabi_score", v4)


if __name__ == "__main__":
    unittest.main()
