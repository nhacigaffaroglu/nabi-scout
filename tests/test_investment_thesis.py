from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from services.company_intelligence_contract import (
    CatalystItem,
    CompanyIntelligenceView,
    DataQualitySection,
    EarningsExpectations,
    EarningsSection,
    FinancialTrendsSection,
    IntelligenceObservation,
    IntelligenceProvenance,
    NewsEvent,
    NewsSection,
    PeerSection,
    ValuationMetric,
    ValuationSection,
)
from services.investment_thesis_builder import build_investment_thesis_view
from services.investment_thesis_change_engine import detect_thesis_changes
from services.investment_thesis_contract import InvestmentThesisView, THESIS_VERSION
from services.investment_thesis_evidence_engine import collect_thesis_evidence
from services.investment_thesis_persistence_service import (
    build_snapshot_payload,
    compute_semantic_identity,
    save_investment_thesis_snapshot,
)
from services.investment_thesis_service import InvestmentThesisService, thesis_view_from_dict


def _obs(
    code: str,
    *,
    direction: Optional[str] = None,
    statement: str = "test",
    evidence: tuple = (),
) -> IntelligenceObservation:
    return IntelligenceObservation(
        code=code,
        status="FACT",
        statement=statement,
        direction=direction,
        evidence=evidence,
        source="test",
        confidence="HIGH",
    )


def _financials(*observations: IntelligenceObservation) -> FinancialTrendsSection:
    return FinancialTrendsSection(
        trends=(),
        observations=observations,
        provenance=IntelligenceProvenance(provider="fmp", data_family="financials"),
    )


def _earnings(*observations: IntelligenceObservation) -> EarningsSection:
    return EarningsSection(
        period="2024-Q1",
        comparison_type="YoY",
        observations=observations,
        expectations=EarningsExpectations(expectations_available=False),
        provenance=IntelligenceProvenance(provider="fmp", data_family="earnings"),
    )


def _valuation(
    *,
    position: str = "NEAR_HISTORICAL_MEDIAN",
    current: float = 25.0,
    median: float = 24.0,
) -> ValuationSection:
    metric = ValuationMetric(
        code="pe_ratio",
        label="F/K",
        current_value=current,
        historical_median=median,
        premium_to_median_pct=4.0,
        position=position,
    )
    return ValuationSection(
        metrics=(metric,),
        observations=(
            IntelligenceObservation(
                code="VALUATION_HISTORICAL_CONTEXT",
                status="FACT",
                statement="F/K tarihsel bağlamda değerlendirildi.",
                evidence=(("position", position),),
                source="fmp",
                confidence="MEDIUM",
            ),
        ),
        provenance=IntelligenceProvenance(provider="fmp", data_family="valuation"),
    )


def _data_quality(**flags: bool) -> DataQualitySection:
    defaults = {
        "company_profile_available": True,
        "financial_history_available": True,
        "quarterly_comparison_available": True,
        "earnings_expectations_available": False,
        "valuation_available": True,
        "historical_valuation_available": True,
        "peer_data_available": True,
        "news_available": True,
        "catalyst_data_available": True,
        "warnings": (),
        "provider_failures": (),
        "partial_sections": (),
        "as_of": "2026-08-01",
    }
    defaults.update(flags)
    return DataQualitySection(**defaults)


def _view(**overrides) -> CompanyIntelligenceView:
    base = dict(
        symbol="AAPL",
        company_name="Apple",
        as_of="2026-08-01",
        business_snapshot=None,
        financial_trends=None,
        earnings=None,
        valuation=None,
        peers=None,
        news=None,
        catalysts=(),
        factual_risks=(),
        data_quality=_data_quality(),
        provenance=(),
    )
    base.update(overrides)
    return CompanyIntelligenceView(**base)


class EvidenceEngineTests(unittest.TestCase):
    def test_margin_expansion_support(self) -> None:
        view = _view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION")))
        evidence = collect_thesis_evidence(view)
        item = next(item for item in evidence if item.code == "GROSS_MARGIN_EXPANSION")
        self.assertEqual(item.polarity, "SUPPORTS")

    def test_margin_compression_weakness(self) -> None:
        view = _view(earnings=_earnings(_obs("OPERATING_MARGIN_COMPRESSION")))
        evidence = collect_thesis_evidence(view)
        item = next(item for item in evidence if item.code == "OPERATING_MARGIN_COMPRESSION")
        self.assertEqual(item.polarity, "WEAKENS")

    def test_revenue_growth_not_auto_quality(self) -> None:
        view = _view(
            financial_trends=_financials(
                _obs("REVENUE_YOY_CHANGE", direction="IMPROVING"),
            )
        )
        evidence = collect_thesis_evidence(view)
        item = next(item for item in evidence if item.code == "REVENUE_YOY_CHANGE")
        self.assertEqual(item.category, "GROWTH")
        self.assertNotEqual(item.category, "BUSINESS")

    def test_debt_increase_not_auto_weakness(self) -> None:
        view = _view(financial_trends=_financials(_obs("DEBT_INCREASE")))
        evidence = collect_thesis_evidence(view)
        item = next(item for item in evidence if item.code == "DEBT_INCREASE")
        self.assertEqual(item.polarity, "NEUTRAL")

    def test_high_valuation_not_sell(self) -> None:
        view = _view(valuation=_valuation(position="ABOVE_HISTORICAL_MEDIAN", current=40, median=20))
        thesis = build_investment_thesis_view(view)
        serialized = json.dumps(thesis.to_dict()).lower()
        self.assertNotIn("sell", serialized)
        self.assertNotIn("strong_sell", serialized)
        self.assertNotIn("sat", serialized)

    def test_low_valuation_not_buy(self) -> None:
        view = _view(valuation=_valuation(position="BELOW_HISTORICAL_MEDIAN", current=10, median=20))
        thesis = build_investment_thesis_view(view)
        serialized = json.dumps(thesis.to_dict()).lower()
        self.assertNotIn("buy", serialized)
        self.assertNotIn("strong_buy", serialized)
        self.assertNotIn("al ", serialized)

    def test_sentiment_news_excluded(self) -> None:
        event = NewsEvent(
            event_id="n1",
            symbol="AAPL",
            headline="Market likes Apple",
            source="news",
            published_at="2026-08-01",
            url="https://example.com",
            summary="positive chatter",
            category="GENERAL",
            materiality="NOISE",
            sentiment="positive",
            impact_domains=(),
            confidence="LOW",
            provenance=IntelligenceProvenance(provider="fmp", data_family="news"),
        )
        view = _view(news=NewsSection(events=(event,), dedupe_count=0, provider_failures=(), provenance=IntelligenceProvenance(provider="fmp", data_family="news")))
        evidence = collect_thesis_evidence(view)
        self.assertEqual(len([item for item in evidence if item.category == "NEWS"]), 0)

    def test_material_regulatory_news_included(self) -> None:
        event = NewsEvent(
            event_id="r1",
            symbol="AAPL",
            headline="Regulatory probe announced",
            source="news",
            published_at="2026-08-01",
            url="https://example.com/r",
            summary="probe",
            category="REGULATORY",
            materiality="MATERIAL",
            sentiment="negative",
            impact_domains=("REGULATORY",),
            confidence="HIGH",
            provenance=IntelligenceProvenance(provider="fmp", data_family="news"),
        )
        view = _view(news=NewsSection(events=(event,), dedupe_count=0, provider_failures=(), provenance=IntelligenceProvenance(provider="fmp", data_family="news")))
        evidence = collect_thesis_evidence(view)
        self.assertTrue(any(item.code.startswith("NEWS_") for item in evidence))

    def test_peer_insufficient_sample(self) -> None:
        view = _view(
            peers=PeerSection(
                peer_selection_method="provider",
                peer_symbols=("MSFT",),
                unavailable_peers=(),
                comparisons=(),
                observations=(),
                limitations=("Emsal örneklemi yetersiz.",),
                provenance=IntelligenceProvenance(provider="fmp", data_family="peers"),
            )
        )
        thesis = build_investment_thesis_view(view)
        self.assertEqual(thesis.confidence, "LOW")

    def test_missing_valuation_lowers_confidence(self) -> None:
        view = _view(
            valuation=None,
            data_quality=_data_quality(valuation_available=False, historical_valuation_available=False),
        )
        thesis = build_investment_thesis_view(view)
        self.assertIn(thesis.confidence, {"LOW", "MEDIUM"})


class ThesisBuilderTests(unittest.TestCase):
    def _rich_view(self) -> CompanyIntelligenceView:
        return _view(
            financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION")),
            earnings=_earnings(
                _obs("REVENUE_ACCELERATION"),
                _obs("FCF_CHANGE"),
            ),
            valuation=_valuation(position="NEAR_HISTORICAL_MEDIAN"),
        )

    def test_support_dominant(self) -> None:
        thesis = build_investment_thesis_view(self._rich_view())
        self.assertEqual(thesis.thesis_status, "SUPPORTED")
        self.assertEqual(thesis.decision_intelligence.evidence_balance, "SUPPORT_DOMINANT")

    def test_balanced_mixed(self) -> None:
        view = _view(
            financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION")),
            earnings=_earnings(_obs("REVENUE_DECELERATION"), _obs("FCF_DETERIORATION")),
        )
        thesis = build_investment_thesis_view(view)
        self.assertIn(thesis.thesis_status, {"MIXED", "WEAKENING", "SUPPORTED"})

    def test_weakness_dominant(self) -> None:
        view = _view(
            earnings=_earnings(
                _obs("REVENUE_DECELERATION"),
                _obs("OPERATING_MARGIN_COMPRESSION"),
                _obs("FCF_DETERIORATION"),
            )
        )
        thesis = build_investment_thesis_view(view)
        self.assertIn(thesis.thesis_status, {"WEAKENING", "MIXED"})

    def test_insufficient_data(self) -> None:
        thesis = build_investment_thesis_view(_view(data_quality=_data_quality(financial_history_available=False)))
        self.assertEqual(thesis.thesis_status, "INSUFFICIENT_DATA")

    def test_deterministic_key_question(self) -> None:
        view = _view(
            valuation=_valuation(position="ABOVE_HISTORICAL_MEDIAN"),
            earnings=_earnings(_obs("REVENUE_DECELERATION")),
        )
        thesis = build_investment_thesis_view(view)
        self.assertIn("büyüme", thesis.key_question.lower())

    def test_no_invented_facts(self) -> None:
        thesis = build_investment_thesis_view(_view())
        self.assertIn("yetersiz", thesis.thesis_summary.lower())

    def test_stable_serialization(self) -> None:
        view = self._rich_view()
        first = build_investment_thesis_view(view).to_dict()
        second = build_investment_thesis_view(view).to_dict()
        self.assertEqual(first, second)


class ValuationTensionTests(unittest.TestCase):
    def test_high_valuation_slowing_growth(self) -> None:
        view = _view(
            valuation=_valuation(position="ABOVE_HISTORICAL_MEDIAN"),
            earnings=_earnings(_obs("REVENUE_DECELERATION")),
        )
        thesis = build_investment_thesis_view(view)
        codes = [item.code for item in thesis.expectation_tensions]
        self.assertIn("HIGH_VALUATION_SLOWING_GROWTH", codes)

    def test_high_valuation_strong_growth(self) -> None:
        view = _view(
            valuation=_valuation(position="ABOVE_HISTORICAL_MEDIAN"),
            earnings=_earnings(_obs("REVENUE_ACCELERATION")),
        )
        thesis = build_investment_thesis_view(view)
        codes = [item.code for item in thesis.expectation_tensions]
        self.assertIn("HIGH_VALUATION_STRONG_GROWTH", codes)

    def test_peer_premium_context(self) -> None:
        view = _view(
            peers=PeerSection(
                peer_selection_method="provider",
                peer_symbols=("MSFT", "GOOG"),
                unavailable_peers=(),
                comparisons=(),
                observations=(
                    _obs("VALUATION_PREMIUM_VS_PEERS"),
                    _obs("GROWTH_BELOW_PEER_MEDIAN"),
                ),
                limitations=(),
                provenance=IntelligenceProvenance(provider="fmp", data_family="peers"),
            )
        )
        thesis = build_investment_thesis_view(view)
        codes = [item.code for item in thesis.expectation_tensions]
        self.assertIn("PEER_PREMIUM_WEAKER_GROWTH", codes)

    def test_missing_valuation(self) -> None:
        thesis = build_investment_thesis_view(_view(valuation=None))
        self.assertEqual(thesis.valuation_context, "VALUATION_UNAVAILABLE")


class RiskCatalystInvalidationTests(unittest.TestCase):
    def test_evidence_linked_risk(self) -> None:
        view = _view(earnings=_earnings(_obs("FCF_DETERIORATION", statement="FCF bozuldu")))
        thesis = build_investment_thesis_view(view)
        self.assertTrue(thesis.risks)
        self.assertEqual(thesis.risks[0].likelihood, "UNKNOWN")

    def test_no_probability_fabrication(self) -> None:
        thesis = build_investment_thesis_view(_view(earnings=_earnings(_obs("FCF_DETERIORATION"))))
        serialized = json.dumps(thesis.to_dict()).lower()
        self.assertNotIn("probability", serialized)
        self.assertNotIn("0.", serialized[:100])

    def test_known_catalyst(self) -> None:
        view = _view(
            catalysts=(
                CatalystItem(
                    code="EARNINGS",
                    catalyst_type="EARNINGS",
                    date="2026-10-30",
                    description="Q4 earnings",
                    source="calendar",
                    confidence="HIGH",
                    status="UPCOMING",
                ),
            )
        )
        thesis = build_investment_thesis_view(view)
        self.assertEqual(len(thesis.catalysts), 1)
        self.assertEqual(thesis.catalysts[0].expected_date, "2026-10-30")

    def test_missing_date_catalyst(self) -> None:
        view = _view(
            catalysts=(
                CatalystItem(
                    code="EARNINGS",
                    catalyst_type="EARNINGS",
                    date=None,
                    description="Q4 earnings",
                    source="calendar",
                    confidence="MEDIUM",
                    status="UPCOMING",
                ),
            )
        )
        thesis = build_investment_thesis_view(view)
        self.assertTrue(thesis.catalysts[0].limitations)

    def test_no_speculative_catalyst(self) -> None:
        thesis = build_investment_thesis_view(_view(catalysts=()))
        self.assertEqual(thesis.catalysts, ())

    def test_margin_invalidation(self) -> None:
        view = _view(financial_trends=_financials(_obs("OPERATING_MARGIN_EXPANSION")))
        thesis = build_investment_thesis_view(view)
        self.assertTrue(any(item.code == "MARGIN_SUPPORT_REVERSAL" for item in thesis.invalidation_conditions))

    def test_growth_valuation_invalidation(self) -> None:
        view = _view(
            valuation=_valuation(position="ABOVE_HISTORICAL_MEDIAN"),
            earnings=_earnings(_obs("REVENUE_DECELERATION")),
        )
        thesis = build_investment_thesis_view(view)
        self.assertTrue(any(item.code == "GROWTH_VALUATION_MISMATCH" for item in thesis.invalidation_conditions))

    def test_leverage_fcf_invalidation(self) -> None:
        view = _view(
            financial_trends=_financials(_obs("DEBT_INCREASE")),
            earnings=_earnings(_obs("FCF_DETERIORATION")),
        )
        thesis = build_investment_thesis_view(view)
        self.assertTrue(any(item.code == "LEVERAGE_FCF_PRESSURE" for item in thesis.invalidation_conditions))

    def test_no_arbitrary_threshold_in_invalidation(self) -> None:
        thesis = build_investment_thesis_view(_view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION"))))
        for condition in thesis.invalidation_conditions:
            self.assertNotIn("15%", condition.statement)
            self.assertNotIn("20%", condition.statement)


class AssumptionTests(unittest.TestCase):
    def test_unverified_assumption(self) -> None:
        view = _view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION")))
        thesis = build_investment_thesis_view(view)
        self.assertTrue(thesis.assumptions)
        self.assertEqual(thesis.assumptions[0].status, "UNVERIFIED")


class ChangeDetectionTests(unittest.TestCase):
    def _thesis(self, *, weakening_codes: List[str] = (), support_codes: List[str] = ()) -> InvestmentThesisView:
        view = _view(
            financial_trends=_financials(*[_obs(code) for code in support_codes]),
            earnings=_earnings(*[_obs(code) for code in weakening_codes]),
        )
        return build_investment_thesis_view(view)

    def test_identical_no_change(self) -> None:
        current = self._thesis(support_codes=["GROSS_MARGIN_EXPANSION"])
        previous = {"thesis_payload": current.to_dict()}
        changes = detect_thesis_changes(current, previous)
        self.assertEqual(changes, ())

    def test_new_weakness(self) -> None:
        current = self._thesis(weakening_codes=["FCF_DETERIORATION"])
        previous_view = self._thesis()
        changes = detect_thesis_changes(current, {"thesis_payload": previous_view.to_dict()})
        self.assertTrue(any(item.code == "NEW_WEAKNESS" for item in changes))

    def test_new_support(self) -> None:
        current = self._thesis(support_codes=["GROSS_MARGIN_EXPANSION"])
        previous_view = self._thesis()
        changes = detect_thesis_changes(current, {"thesis_payload": previous_view.to_dict()})
        self.assertTrue(any(item.code == "NEW_SUPPORT" for item in changes))

    def test_valuation_context_changed(self) -> None:
        current = build_investment_thesis_view(_view(valuation=_valuation(position="ABOVE_HISTORICAL_MEDIAN")))
        previous = build_investment_thesis_view(_view(valuation=_valuation(position="BELOW_HISTORICAL_MEDIAN")))
        changes = detect_thesis_changes(current, {"thesis_payload": previous.to_dict()})
        self.assertTrue(any(item.code == "VALUATION_CONTEXT_CHANGED" for item in changes))

    def test_timestamp_only_ignored_in_dedupe(self) -> None:
        view = build_investment_thesis_view(_view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION"))))
        first = compute_semantic_identity(view)
        second = compute_semantic_identity(view)
        self.assertEqual(first, second)


class PersistenceTests(unittest.TestCase):
    def test_schema_rls_contract(self) -> None:
        with open("database/migration_investment_thesis_snapshots.sql", encoding="utf-8") as handle:
            sql = handle.read()
        self.assertIn("investment_thesis_snapshots", sql)
        self.assertIn("enable row level security", sql.lower())
        self.assertIn("authenticated", sql.lower())
        self.assertNotIn("anon", sql.lower())

    def test_save_snapshot(self) -> None:
        view = build_investment_thesis_view(_view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION"))))
        repo = MagicMock()
        repo.get_latest.return_value = None
        repo.append_snapshot.return_value = {"id": "1"}
        result = save_investment_thesis_snapshot(repo, view)
        self.assertTrue(result.saved)
        repo.append_snapshot.assert_called_once()

    def test_dedupe_identical(self) -> None:
        view = build_investment_thesis_view(_view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION"))))
        repo = MagicMock()
        identity = compute_semantic_identity(view)
        repo.get_latest.return_value = {"semantic_identity": identity}
        result = save_investment_thesis_snapshot(repo, view)
        self.assertTrue(result.skipped_duplicate)
        repo.append_snapshot.assert_not_called()

    def test_save_changed_thesis(self) -> None:
        view = build_investment_thesis_view(_view(earnings=_earnings(_obs("FCF_DETERIORATION"))))
        repo = MagicMock()
        repo.get_latest.return_value = {"semantic_identity": "different"}
        repo.append_snapshot.return_value = {"id": "2"}
        result = save_investment_thesis_snapshot(repo, view)
        self.assertTrue(result.saved)

    def test_history_ordering(self) -> None:
        from repositories.investment_thesis_repository import InvestmentThesisRepository

        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"captured_at": "2026-08-02"}, {"captured_at": "2026-08-01"}]
        )
        repo = InvestmentThesisRepository(client)
        rows = repo.get_recent_history("AAPL", limit=5)
        self.assertEqual(len(rows), 2)

    def test_bounded_history(self) -> None:
        from repositories.investment_thesis_repository import InvestmentThesisRepository

        client = MagicMock()
        limit_holder: Dict[str, int] = {}

        def _limit(value: int):
            limit_holder["value"] = value
            return client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value

        client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.side_effect = _limit
        client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        repo = InvestmentThesisRepository(client)
        repo.get_recent_history("AAPL", limit=100)
        self.assertLessEqual(limit_holder["value"], 25)

    def test_no_wealth_nabi_participation_writes(self) -> None:
        repo = MagicMock()
        view = build_investment_thesis_view(_view())
        save_investment_thesis_snapshot(repo, view)
        table_name = repo.append_snapshot.call_args[0][0]["symbol"]
        self.assertEqual(table_name, "AAPL")
        self.assertEqual(repo.append_snapshot.call_args[0][0]["thesis_version"], THESIS_VERSION)


class AdversarialGateTests(unittest.TestCase):
    def test_missing_section_no_fabrication(self) -> None:
        thesis = build_investment_thesis_view(_view())
        self.assertEqual(thesis.thesis_status, "INSUFFICIENT_DATA")
        self.assertEqual(len(thesis.supporting_evidence), 0)

    def test_nabi_decision_does_not_force_status(self) -> None:
        view = _view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION")))
        thesis = build_investment_thesis_view(
            view,
            candidate={"decision": "ARAŞTIR", "nabi_score": 40},
        )
        self.assertNotEqual(thesis.thesis_status, "ARAŞTIR")

    def test_participation_does_not_force_status(self) -> None:
        view = _view(earnings=_earnings(_obs("FCF_DETERIORATION")))
        thesis = build_investment_thesis_view(view, participation_context="Katılım durumu: UYGUN")
        self.assertIn(thesis.thesis_status, {"WEAKENING", "MIXED", "INSUFFICIENT_DATA"})

    def test_low_confidence_not_high_in_summary(self) -> None:
        thesis = build_investment_thesis_view(_view())
        self.assertEqual(thesis.confidence, "LOW")
        self.assertIn("yetersiz", thesis.thesis_summary.lower())

    def test_provider_failure_degrades_confidence(self) -> None:
        view = _view(
            financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION")),
            data_quality=_data_quality(provider_failures=("news",)),
        )
        thesis = build_investment_thesis_view(view)
        self.assertIn(thesis.confidence, {"LOW", "MEDIUM"})

    def test_no_secrets_in_serialization(self) -> None:
        thesis = build_investment_thesis_view(_view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION"))))
        serialized = json.dumps(thesis.to_dict()).lower()
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("service_role", serialized)

    def test_no_price_target(self) -> None:
        thesis = build_investment_thesis_view(_view(valuation=_valuation()))
        serialized = json.dumps(thesis.to_dict()).lower()
        self.assertNotIn("price target", serialized)
        self.assertNotIn("hedef fiyat", serialized)

    def test_repeated_inputs_identical(self) -> None:
        view = _view(
            financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION")),
            earnings=_earnings(_obs("REVENUE_ACCELERATION")),
        )
        a = InvestmentThesisService().build_view(view).to_dict()
        b = InvestmentThesisService().build_view(view).to_dict()
        self.assertEqual(a, b)

    def test_roundtrip_dict(self) -> None:
        original = build_investment_thesis_view(_view(financial_trends=_financials(_obs("GROSS_MARGIN_EXPANSION"))))
        restored = thesis_view_from_dict(original.to_dict())
        self.assertEqual(restored.thesis_status, original.thesis_status)
        self.assertEqual(len(restored.supporting_evidence), len(original.supporting_evidence))


class InvestmentThesisUiTests(unittest.TestCase):
    def test_ui_turkish_not_raw_codes(self) -> None:
        source = open("components/investment_thesis_ui.py", encoding="utf-8").read()
        self.assertIn("Yatırım Tezi", source)
        self.assertIn("Teknik ayrıntılar", source)
        body = source.split("render_investment_thesis_section", 1)[1]
        self.assertNotIn("VALUATION_DEMANDING", body.split("Teknik ayrıntılar")[0])


if __name__ == "__main__":
    unittest.main()
