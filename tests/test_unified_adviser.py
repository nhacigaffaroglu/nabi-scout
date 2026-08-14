from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from services.company_intelligence_data import (
    CompanyProviderBundle,
    load_company_provider_bundle,
    max_expected_provider_calls,
)
from services.investment_thesis_contract import InvestmentThesisView, THESIS_VERSION
from services.portfolio_company_fit_engine import assess_portfolio_company_fit
from services.unified_research_contract import WealthExposureContext
from services.unified_research_service import UnifiedResearchService
from services.unified_research_serializer import serialize_investment_thesis_for_adviser
from services.wealth_adviser_contract import ADVISER_LLM_INPUT_SCHEMA_VERSION
from services.wealth_adviser_prompt import (
    approximate_payload_size_bytes,
    build_llm_input_payload,
    extract_focus_symbol,
)
from services.wealth_adviser_output_validator import validate_adviser_response
from services.wealth_adviser_contract import AdviserResponse
from services.wealth_exposure_bridge import build_wealth_exposure_context
from tests.test_wealth_adviser_llm import _brief


class WealthExposureBridgeTests(unittest.TestCase):
    def test_not_held(self) -> None:
        exposure = build_wealth_exposure_context(None, "AAPL")
        self.assertFalse(exposure.held)
        self.assertIn("mevcut değil", exposure.limitations[0].lower())

    def test_held_weight(self) -> None:
        portfolio = MagicMock()
        row = MagicMock()
        row.symbol = "AAPL"
        row.is_cash = False
        row.quantity = 10.0
        row.market_value = 1000.0
        row.cost_basis = 800.0
        row.weight_pct = 20.0
        row.account_name = "Broker"
        portfolio.positions = [row]
        exposure = build_wealth_exposure_context(portfolio, "AAPL")
        self.assertTrue(exposure.held)
        self.assertEqual(exposure.portfolio_weight_pct, 20.0)


class PortfolioFitTests(unittest.TestCase):
    def test_weakening_high_exposure(self) -> None:
        thesis = InvestmentThesisView(
            symbol="AAPL",
            company_name="Apple",
            as_of="t",
            thesis_version=THESIS_VERSION,
            thesis_status="WEAKENING",
            thesis_summary="s",
            key_question="q",
            supporting_evidence=(),
            weakening_evidence=(),
            risks=(),
            catalysts=(),
            invalidation_conditions=(),
            assumptions=(),
            valuation_context="VALUATION_DEMANDING",
            earnings_context="EARNINGS_WEAKENING",
            peer_context=None,
            news_context=None,
        )
        exposure = WealthExposureContext(
            symbol="AAPL",
            held=True,
            quantity=1,
            market_value=1000,
            portfolio_weight_pct=25.0,
            cost_basis=900,
            unrealized_pl=100,
            account_names=("Broker",),
            concentration_context="yüksek",
        )
        fit = assess_portfolio_company_fit(thesis, exposure)
        self.assertEqual(fit[0].code, "THESIS_WEAKENING_HIGH_EXPOSURE")


class UnifiedAdviserPromptTests(unittest.TestCase):
    def test_v3_schema_version(self) -> None:
        payload = build_llm_input_payload(_brief(), user_question="Q").to_dict()
        self.assertEqual(payload["schema_version"], ADVISER_LLM_INPUT_SCHEMA_VERSION)
        self.assertIn("wealth-adviser-llm-input-v3", payload["schema_version"])

    def test_extract_symbol_from_question(self) -> None:
        self.assertEqual(
            extract_focus_symbol("AAPL yatırımımı bugün yeniden değerlendir."),
            "AAPL",
        )

    def test_payload_size_bounded(self) -> None:
        payload = build_llm_input_payload(_brief(), user_question="Q").to_dict()
        size = approximate_payload_size_bytes(payload)
        self.assertLess(size, 120_000)


class GoldenQuestionDeterministicTests(unittest.TestCase):
    def test_exact_trade_request_rejected(self) -> None:
        brief = _brief()
        result = validate_adviser_response(
            AdviserResponse(
                answer="AAPL'ı %40'a indir ve VOO al.",
                key_points=(),
                referenced_finding_ids=(),
                limitations=(),
                follow_up_questions=(),
                safety_flags=(),
                model_name="test",
                generated_at="t",
                grounded=False,
            ),
            brief.context,
        )
        self.assertFalse(result.valid)

    def test_option_level_guidance_allowed(self) -> None:
        brief = _brief()
        result = validate_adviser_response(
            AdviserResponse(
                answer=(
                    "Yoğunlaşmayı azaltmak istiyorsanız yeni katkıları farklı "
                    "varlık sınıflarına yönlendirme seçeneğini değerlendirebilirsiniz."
                ),
                key_points=(),
                referenced_finding_ids=(),
                limitations=(),
                follow_up_questions=(),
                safety_flags=(),
                model_name="test",
                generated_at="t",
                grounded=False,
            ),
            brief.context,
        )
        self.assertTrue(result.valid)

    def test_thesis_serialization_no_secrets(self) -> None:
        thesis = InvestmentThesisView(
            symbol="AAPL",
            company_name="Apple",
            as_of="t",
            thesis_version=THESIS_VERSION,
            thesis_status="SUPPORTED",
            thesis_summary="s",
            key_question="q",
            supporting_evidence=(),
            weakening_evidence=(),
            risks=(),
            catalysts=(),
            invalidation_conditions=(),
            assumptions=(),
            valuation_context="VALUATION_NEUTRAL",
            earnings_context="EARNINGS_SUPPORT",
            peer_context=None,
            news_context=None,
        )
        serialized = json.dumps(serialize_investment_thesis_for_adviser(thesis))
        self.assertNotIn("api_key", serialized.lower())


class FmpCallBudgetTests(unittest.TestCase):
    def test_max_expected_calls_at_most_15(self) -> None:
        self.assertLessEqual(max_expected_provider_calls(peer_count=4), 15)

    def test_cold_load_call_count(self) -> None:
        fmp = MagicMock()
        fmp.profile.return_value = {"companyName": "Apple"}
        fmp.income_statement_quarterly.return_value = []
        fmp.balance_sheet_quarterly.return_value = []
        fmp.cash_flow_quarterly.return_value = []
        fmp.ratios_ttm.return_value = {}
        fmp.key_metrics_ttm.return_value = {}
        fmp.ratios.return_value = []
        fmp.key_metrics.return_value = []
        fmp.stock_peers.return_value = ["MSFT", "GOOG", "META"]
        fmp.stock_news.return_value = []
        fmp.earnings_surprises.return_value = []
        fmp.earnings_calendar.return_value = []
        fmp.ratios_ttm.side_effect = lambda symbol: {}
        bundle = load_company_provider_bundle(fmp, "AAPL")
        total = sum(bundle.call_counts.values())
        self.assertLessEqual(total, 15)
        self.assertNotIn("quote", bundle.call_counts)
        self.assertNotIn("income_annual", bundle.call_counts)
        self.assertNotIn("analyst_estimates", bundle.call_counts)
        self.assertTrue(
            all(not key.startswith("peer_profile:") for key in bundle.call_counts)
        )


if __name__ == "__main__":
    unittest.main()
