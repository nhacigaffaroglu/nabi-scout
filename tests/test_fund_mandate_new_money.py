from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from services.fund_decision_readiness import evaluate_fund_eight_e_readiness
from services.fund_product_contract import (
    PILOT_FUND_SYMBOLS,
    REGION_INTERNATIONAL_EX_US,
    OfficialFundMandate,
)
from services.official_sp_funds_product import (
    resolve_official_fund_mandates,
    validate_canonical_mandate,
)
from services.portfolio_economic_exposure import (
    ExposureEvidenceSource,
    classify_instrument_exposure,
)
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    DECISION_WATCH,
)
from services.portfolio_security_decision_engine import (
    evaluate_portfolio_security_decision,
    supports_portfolio_decision,
)
from services.portfolio_security_decision_contract import PortfolioSecurityContext
from services.security_intelligence_contract import STATE_WATCH
from services.wealth_new_money_allocation import (
    REASON_EXPOSURE_INCREASE_NOT_ALLOWED,
    allocate_new_money,
)
from tests.test_nabi_adviser_8f import _psd
from tests.test_portfolio_economic_exposure import _equity, _etf
from tests.test_wealth_new_money_allocation import _fx, _policy, _row, _view
from tests.test_wealth_new_money_allocation import _exposure_policy


NEW_MONEY = Path("services/wealth_new_money_allocation.py")
PRODUCT = Path("services/official_sp_funds_product.py")


class _FailingProvider:
    def supports(self, symbol: str) -> bool:
        raise RuntimeError("official source unavailable")

    def mandate(self, symbol: str) -> OfficialFundMandate:
        raise RuntimeError("official source unavailable")


def _ana_view():
    return _view(
        [
            _row("AAPL", market_value=800, weight_pct=8, price=100),
            _row("CRM", market_value=800, weight_pct=8, price=100),
            _row("ASELS", market_value=500, weight_pct=5, price=100),
            _row("BIMAS", market_value=500, weight_pct=5, price=100),
            _row("TUPRS", market_value=400, weight_pct=4, price=100),
            _row("SPUS", market_value=2500, weight_pct=25, price=100, asset_class="etf"),
            _row("SPSK", market_value=1500, weight_pct=15, price=100, asset_class="etf"),
            _row("SPRE", market_value=1000, weight_pct=10, price=100, asset_class="etf"),
            _row("SPWO", market_value=1000, weight_pct=10, price=100, asset_class="etf"),
            _row("TSLA", market_value=1000, weight_pct=10, price=100),
        ]
    )


class MandateResolutionTests(unittest.TestCase):
    def test_automatic_pilot_layers(self) -> None:
        resolved = resolve_official_fund_mandates(PILOT_FUND_SYMBOLS)
        self.assertEqual(resolved["SPUS"].primary_layer, "equity")
        self.assertEqual(resolved["SPSK"].primary_layer, "sukuk")
        self.assertEqual(resolved["SPRE"].primary_layer, "real_estate")
        self.assertEqual(resolved["SPWO"].primary_layer, "equity")
        self.assertEqual(resolved["SPWO"].region, REGION_INTERNATIONAL_EX_US)
        self.assertNotIn("HLAL", resolved)

    def test_unsupported_and_provider_failure_fail_closed(self) -> None:
        self.assertEqual(resolve_official_fund_mandates(("HLAL", "UNKNOWNETF")), {})
        self.assertEqual(
            resolve_official_fund_mandates(PILOT_FUND_SYMBOLS, provider=_FailingProvider()),
            {},
        )

    def test_explicit_valid_overrides_canonical(self) -> None:
        canonical = resolve_official_fund_mandates(("SPUS",))["SPUS"]
        override = OfficialFundMandate(
            symbol="SPUS",
            primary_layer="sukuk",
            region="GLOBAL",
            vehicle="SUKUK",
            confidence="HIGH",
            source="test",
            source_url="test",
            evidence_excerpt="explicit test overlay",
        )
        resolved = resolve_official_fund_mandates(("SPUS",), explicit={"SPUS": override})
        self.assertEqual(resolved["SPUS"].primary_layer, "sukuk")
        self.assertNotEqual(resolved["SPUS"].primary_layer, canonical.primary_layer)

    def test_invalid_override_rejected(self) -> None:
        self.assertIsNone(validate_canonical_mandate("equity"))
        self.assertIsNone(validate_canonical_mandate({"primary_layer": "equity"}))
        resolved = resolve_official_fund_mandates(("SPUS",), explicit={"SPUS": "equity"})
        self.assertNotIn("SPUS", resolved)


class NewMoneyWiringTests(unittest.TestCase):
    def test_live_path_resolves_without_fund_mandates_kwarg(self) -> None:
        view = _ana_view()
        before = classify_instrument_exposure(_etf("SPUS"))
        self.assertFalse(before.evidence_complete)
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", before.limitations)
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=view,
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
        )
        self.assertNotIn("fund_mandates=", "allocate_new_money call")
        classified = {
            symbol: classify_instrument_exposure(
                _etf(symbol),
                fund_mandates=resolve_official_fund_mandates((symbol,)),
            )
            for symbol in PILOT_FUND_SYMBOLS
        }
        self.assertTrue(all(item.evidence_complete for item in classified.values()))
        self.assertEqual(classified["SPUS"].economic_exposures[0].exposure_bucket, "equity")
        self.assertEqual(classified["SPSK"].economic_exposures[0].exposure_bucket, "sukuk")
        self.assertEqual(classified["SPRE"].economic_exposures[0].exposure_bucket, "real_estate")
        self.assertEqual(classified["SPWO"].economic_exposures[0].exposure_bucket, "equity")
        self.assertEqual(
            classified["SPUS"].economic_exposures[0].evidence_source,
            ExposureEvidenceSource.OFFICIAL_FUND_MANDATE,
        )
        self.assertNotIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)
        self.assertFalse(plan.hybrid_allocation_active)
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertEqual(plan.residual_cash, Decimal("60000"))

    def test_unsupported_fund_stays_incomplete(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_view(
                [_row("HLAL", market_value=1000, weight_pct=100, price=100, asset_class="etf")]
            ),
            policy=_exposure_policy(equity=100),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
        )
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)

    def test_provider_failure_stays_incomplete(self) -> None:
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_view(
                [_row("SPUS", market_value=1000, weight_pct=100, price=100, asset_class="etf")]
            ),
            policy=_exposure_policy(equity=100),
            conversion=_fx(),
            fund_mandate_provider=_FailingProvider(),
            enable_hybrid_exposure_allocation=False,
        )
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", plan.limitations)

    def test_fund_intelligence_missing_still_blocks_increase(self) -> None:
        eight_e = evaluate_fund_eight_e_readiness(
            symbol="SPUS",
            fund_intelligence_ready=False,
            participation_acceptable=False,
            economic_exposure_available=True,
        )
        self.assertEqual(eight_e["decision"], DECISION_INSUFFICIENT_DATA)
        self.assertFalse(eight_e["exposure_increase_allowed"])
        plan = allocate_new_money(
            available_amount=Decimal("60000"),
            amount_currency="TRY",
            portfolio_view=_ana_view(),
            policy=_exposure_policy(equity=70, sukuk=15, real_estate=10, cash=5),
            conversion=_fx(),
            enable_hybrid_exposure_allocation=False,
            security_decisions=(
                _psd("SPUS", DECISION_INSUFFICIENT_DATA, increase=False),
                _psd("SPSK", DECISION_INSUFFICIENT_DATA, increase=False),
                _psd("SPRE", DECISION_INSUFFICIENT_DATA, increase=False),
                _psd("SPWO", DECISION_INSUFFICIENT_DATA, increase=False),
            ),
        )
        self.assertEqual(plan.total_allocated, Decimal("0"))
        self.assertTrue(
            any(row.reason_code == REASON_EXPOSURE_INCREASE_NOT_ALLOWED for row in plan.skipped)
            or plan.residual_cash == Decimal("60000")
        )

    def test_equity_and_bist_isolation(self) -> None:
        aapl = classify_instrument_exposure(_equity("AAPL"))
        crm = classify_instrument_exposure(_equity("CRM"))
        asels = classify_instrument_exposure(_equity("ASELS"))
        self.assertTrue(aapl.evidence_complete)
        self.assertTrue(crm.evidence_complete)
        self.assertTrue(asels.evidence_complete)
        self.assertEqual(aapl.economic_exposures[0].exposure_bucket, "equity")
        self.assertTrue(supports_portfolio_decision(symbol="AAPL", instrument_type="EQUITY", market="US"))
        self.assertTrue(supports_portfolio_decision(symbol="ASELS", instrument_type="EQUITY", market="BIST"))
        watch = evaluate_portfolio_security_decision(
            PortfolioSecurityContext(
                symbol="CRM",
                participation_status="Uygun",
                research_allowed=True,
                si_state=STATE_WATCH,
                si_score=53.3,
                is_holding=True,
                instrument_type="EQUITY",
                market="US",
            )
        )
        self.assertNotEqual(watch.decision, DECISION_INSUFFICIENT_DATA)
        self.assertNotIn("FUND_INTELLIGENCE_MISSING", watch.blocking_reasons)
        source = NEW_MONEY.read_text(encoding="utf-8")
        self.assertNotIn('if symbol == "SPUS"', source)
        self.assertNotIn("PILOT_FUND_SYMBOLS", source)
        self.assertIn("resolve_official_fund_mandates", source)
        self.assertNotIn("FMPClient", PRODUCT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
