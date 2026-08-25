from __future__ import annotations

import unittest
from typing import Any

from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.global_participation_reconciliation import assess_from_cached_evidence
from services.participation_business_contract import BUSINESS_SCREEN_OUTCOME_FAIL
from services.participation_cached_evidence_resolver import (
    LIMITATION_BROAD_PARTITION,
    LIMITATION_COMPANY_FACTS_NO_DIMENSIONAL_SEGMENTS,
    LIMITATION_MAPPING_AMBIGUOUS,
    LIMITATION_MISSING_DENOMINATOR,
    NPR_STATE_MISSING,
    NPR_STATE_POSITIVE,
    NPR_STATE_PROVEN_ZERO,
    REASON_BUSINESS_NPR_INSUFFICIENT,
    REASON_BUSINESS_SIC_REVIEW,
    REASON_FINANCIAL_NPR_INSUFFICIENT,
    REASON_MISSING_PROHIBITED_REVENUE,
    classify_npr_limitations,
    classify_unresolved_npr_reasons,
    npr_state_from_amount,
    resolve_business_npr_from_cached_company_facts,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_REVIEW_REQUIRED,
)
from services.participation_revenue_attribution_contract import (
    ATTRIBUTION_SUCCESS,
    MAPPING_AMBIGUOUS,
    PARTITION_COMPLETE,
    RevenueAttributionItem,
    RevenueAttributionView,
)
from services.participation_revenue_granularity import finalize_attribution_view
from services.sec_company_facts_evidence import SOURCE_SEC_COMPANY_FACTS
from services.sec_participation_evidence_population import AssessedEquityIdentity
from tests.test_global_participation_reconciliation import _business_pass, _snapshot
from tests.test_participation_revenue_granularity import _item, _view


END = "2025-12-31"
FILED = "2026-02-17"
ACCN = "0001234567-26-000001"


def _duration(val: float, *, segment: str | None = None, end: str = END) -> dict[str, Any]:
    item: dict[str, Any] = {
        "form": "10-K",
        "start": "2025-01-01",
        "end": end,
        "val": val,
        "filed": FILED,
        "accn": ACCN,
    }
    if segment:
        item["segment"] = segment
    return item


def _instant(val: float) -> dict[str, Any]:
    return {
        "units": {
            "USD": [
                {
                    "form": "10-K",
                    "end": END,
                    "val": val,
                    "filed": FILED,
                    "accn": ACCN,
                }
            ]
        }
    }


def _facts_payload(
    *,
    revenue: float = 100.0,
    segments: tuple[tuple[str, float], ...] = (),
    sic: str | None = None,
    period: str = END,
) -> dict[str, Any]:
    revenue_items = [_duration(revenue, end=period)]
    for name, amount in segments:
        revenue_items.append(_duration(amount, segment=name, end=period))
    payload: dict[str, Any] = {
        "cik": 320193,
        "entityName": "Fixture Corp",
        "facts": {
            "dei": {},
            "us-gaap": {
                "Revenues": {"units": {"USD": revenue_items}},
                "Assets": _instant(500.0),
                "LongTermDebtNoncurrent": _instant(10.0),
                "CashAndCashEquivalentsAtCarryingValue": _instant(20.0),
                "AccountsReceivableNetCurrent": _instant(15.0),
                "MarketableSecuritiesCurrent": _instant(5.0),
            },
        },
    }
    if sic:
        payload["sic"] = sic
    return payload


def _financials(period: str = END, revenue: float = 100.0) -> dict[str, Any]:
    return {
        "revenue": revenue,
        "financial_period_end": period,
        "financial_currency": "USD",
        "financial_taxonomy": "us-gaap",
    }


class ClassificationContractTests(unittest.TestCase):
    def test_missing_is_not_zero(self) -> None:
        self.assertEqual(npr_state_from_amount(None), NPR_STATE_MISSING)
        self.assertNotEqual(npr_state_from_amount(None), NPR_STATE_PROVEN_ZERO)

    def test_zero_without_proof_is_insufficient(self) -> None:
        self.assertEqual(npr_state_from_amount(0.0, proven_zero=False), "INSUFFICIENT")

    def test_proven_zero_requires_flag(self) -> None:
        self.assertEqual(npr_state_from_amount(0.0, proven_zero=True), NPR_STATE_PROVEN_ZERO)

    def test_native_unresolved_reasons(self) -> None:
        reasons = classify_unresolved_npr_reasons(
            npr_amount=None,
            missing_capabilities=("prohibited_revenue_inference",),
            financial_npr_outcome="INSUFFICIENT_DATA",
            business_npr_outcome="INSUFFICIENT_DATA",
            limitations=(LIMITATION_BROAD_PARTITION,),
        )
        self.assertIn(REASON_MISSING_PROHIBITED_REVENUE, reasons)
        self.assertIn(REASON_FINANCIAL_NPR_INSUFFICIENT, reasons)
        self.assertIn(REASON_BUSINESS_NPR_INSUFFICIENT, reasons)
        self.assertIn(LIMITATION_BROAD_PARTITION, reasons)

    def test_limitations_use_existing_strings(self) -> None:
        found = classify_npr_limitations(
            [
                "SEC toplam gelir mevcut ancak yapılandırılmış segment ayrımı bulunamadı.",
                LIMITATION_MAPPING_AMBIGUOUS,
                LIMITATION_MISSING_DENOMINATOR,
            ]
        )
        self.assertEqual(
            found,
            (LIMITATION_MAPPING_AMBIGUOUS, LIMITATION_MISSING_DENOMINATOR),
        )


class CachedCompanyFactsResolverTests(unittest.TestCase):
    def test_company_facts_without_segments_leave_npr_missing(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "NVDA",
            _facts_payload(),
            sec_financials=_financials(),
            source_identifier="digest-nvda",
            cik="0001045810",
        )
        self.assertIsNone(result.npr_amount)
        self.assertEqual(result.npr_state, NPR_STATE_MISSING)
        self.assertFalse(result.company_facts_can_answer_npr)
        self.assertFalse(result.company_facts_can_answer_sic)
        self.assertFalse(result.company_facts_can_answer_description)
        self.assertIn(REASON_MISSING_PROHIBITED_REVENUE, result.unresolved_reasons)
        self.assertIn(LIMITATION_COMPANY_FACTS_NO_DIMENSIONAL_SEGMENTS, result.limitations)
        self.assertEqual(result.period, END)
        self.assertEqual(result.currency, "USD")

    def test_period_mismatch_drops_foreign_segments(self) -> None:
        payload = _facts_payload(
            segments=(("Subscription and Support", 95.0), ("Licensing", 5.0)),
            period="2024-12-31",
        )
        result = resolve_business_npr_from_cached_company_facts(
            "TEST",
            payload,
            sec_financials=_financials(period=END),
            source_identifier="digest-period",
        )
        self.assertEqual(result.period, END)
        self.assertEqual(result.business_evidence.revenue_segments, ())
        self.assertIsNone(result.npr_amount)

    def test_provenance_is_auditable(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "MSFT",
            _facts_payload(),
            sec_financials=_financials(),
            source_identifier="abc123",
            cik="0000789019",
        )
        npr_prov = result.provenance[0]
        self.assertEqual(npr_prov.source_type, SOURCE_SEC_COMPANY_FACTS)
        self.assertEqual(npr_prov.source_identifier, "abc123")
        self.assertEqual(npr_prov.period, END)
        self.assertEqual(npr_prov.filing_accession, ACCN)
        self.assertEqual(npr_prov.field, "non_permissible_revenue")
        self.assertEqual(npr_prov.raw_or_derived, "derived")
        self.assertTrue(npr_prov.resolution_reason)

    def test_safe_zero_requires_positive_attribution_evidence(self) -> None:
        attr = finalize_attribution_view(
            _view(
                items=(
                    _item("Subscription and Support", 95.0),
                    _item("Professional Services and Other", 5.0),
                )
            )
        )
        result = resolve_business_npr_from_cached_company_facts(
            "CRM",
            _facts_payload(),
            sec_financials=_financials(),
            source_identifier="digest-crm",
            revenue_attribution=attr,
        )
        self.assertEqual(result.npr_amount, 0.0)
        self.assertEqual(result.npr_state, NPR_STATE_PROVEN_ZERO)
        self.assertTrue(result.company_facts_can_answer_npr)
        self.assertNotIn(REASON_MISSING_PROHIBITED_REVENUE, result.unresolved_reasons)

    def test_broad_partition_is_not_safe_zero(self) -> None:
        attr = finalize_attribution_view(
            _view(
                items=(
                    _item("Google Services", 80.0, axis="StatementBusinessSegmentsAxis"),
                    _item("Google Cloud", 20.0, axis="StatementBusinessSegmentsAxis"),
                ),
                axis="StatementBusinessSegmentsAxis",
            )
        )
        result = resolve_business_npr_from_cached_company_facts(
            "GOOGL",
            _facts_payload(),
            sec_financials=_financials(),
            revenue_attribution=attr,
        )
        self.assertIsNone(result.npr_amount)
        self.assertEqual(result.npr_state, NPR_STATE_MISSING)
        self.assertIn(LIMITATION_BROAD_PARTITION, result.limitations)

    def test_ambiguous_mapping_is_not_zero(self) -> None:
        items = (
            RevenueAttributionItem(
                reported_label="Other",
                normalized_label="other",
                concept="us-gaap:Revenues",
                axis="ProductOrServiceAxis",
                member="OtherMember",
                amount=100.0,
                mapping_status=MAPPING_AMBIGUOUS,
                msci_category="",
                mapping_rule_id="test",
                rationale="test",
                source="https://sec.gov",
            ),
        )
        attr = RevenueAttributionView(
            symbol="ACN",
            cik="1",
            methodology="msci_islamic_index_series",
            methodology_version="2025-05",
            screening_period=END,
            filing_accession=ACCN,
            filing_form="10-K",
            filing_date=FILED,
            filing_url="https://sec.gov",
            primary_document="t.htm",
            denominator_name="Revenues",
            denominator_value=100.0,
            currency="USD",
            selected_axis="ProductOrServiceAxis",
            partition_status=PARTITION_COMPLETE,
            partition_sum=100.0,
            partition_coverage=1.0,
            items=items,
            prohibited_revenue=0.0,
            status=ATTRIBUTION_SUCCESS,
        )
        result = resolve_business_npr_from_cached_company_facts(
            "ACN",
            _facts_payload(),
            sec_financials=_financials(),
            revenue_attribution=attr,
        )
        self.assertIsNone(result.npr_amount)
        self.assertIn(LIMITATION_MAPPING_AMBIGUOUS, result.limitations)

    def test_explicit_prohibited_segment_is_positive(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "TEST",
            _facts_payload(segments=(("Casino operations", 12.0), ("Software", 88.0))),
            sec_financials=_financials(),
        )
        self.assertEqual(result.npr_amount, 12.0)
        self.assertEqual(result.npr_state, NPR_STATE_POSITIVE)

    def test_prohibited_sic_fails_business(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "TEST",
            _facts_payload(sic="7990"),
            sec_financials=_financials(),
        )
        self.assertTrue(result.company_facts_can_answer_sic)
        self.assertEqual(result.business_screen.overall_outcome, BUSINESS_SCREEN_OUTCOME_FAIL)
        sic_rule = next(r for r in result.business_screen.rule_results if "sic" in r.rule_id)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_FAIL)

    def test_ambiguous_business_sic_stays_review(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "TEST",
            _facts_payload(sic="6211"),
            sec_financials=_financials(),
        )
        sic_rule = next(r for r in result.business_screen.rule_results if "sic" in r.rule_id)
        self.assertEqual(sic_rule.outcome, RULE_OUTCOME_REVIEW_REQUIRED)
        self.assertIn(REASON_BUSINESS_SIC_REVIEW, result.unresolved_reasons)


class HalalFirewallCompatibilityTests(unittest.TestCase):
    def test_kontrol_et_from_missing_npr_is_not_actionable(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "NVDA",
            _facts_payload(),
            sec_financials=_financials(),
        )
        self.assertEqual(result.npr_state, NPR_STATE_MISSING)
        self.assertFalse(
            is_actionable_opportunity(
                {
                    "symbol": "NVDA",
                    "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                    "decision": "GÜÇLÜ ADAY",
                    "current_price": 120.0,
                    "data_completeness": 90,
                    "nabi_score": 80,
                    "last_scanned_at": "2026-08-01T00:00:00+00:00",
                    "research_status": "TAMAMLANDI",
                }
            )
        )


class ApprovedRejectedAnchorTests(unittest.TestCase):
    def _evidence(self, symbol: str, cik: str):
        from services.sec_company_facts_evidence import build_company_facts_evidence

        return build_company_facts_evidence(
            symbol=symbol,
            cik=cik,
            raw_payload=_facts_payload(),
            http_status=200,
        )

    def test_approved_anchor_preserved_when_snapshot_npr_is_proven(self) -> None:
        evidence = self._evidence("CRM", "0001108524")
        from services.sec_financial_client import SECFinancialClient

        extracted = SECFinancialClient(contact_email="cache-replay@localhost").extract_financials(
            evidence.raw_payload
        )
        item = assess_from_cached_evidence(
            identity=AssessedEquityIdentity(
                symbol="CRM",
                cik="0001108524",
                cik_source="snapshot",
                fetchable=True,
            ),
            evidence=evidence,
            snapshot=_snapshot("CRM", "0001108524", PARTICIPATION_STATUS_UYGUN),
            extracted=extracted,
        )
        self.assertEqual(item.old_status, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(item.new_status, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(item.result.financial_inputs.non_permissible_revenue, 0.0)

    def test_cache_only_does_not_invent_approved_zero(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "CRM",
            _facts_payload(),
            sec_financials=_financials(),
        )
        self.assertIsNone(result.npr_amount)
        self.assertEqual(result.npr_state, NPR_STATE_MISSING)

    def test_rejected_financial_fail_is_not_converted_to_uygun(self) -> None:
        payload = _facts_payload()
        payload["facts"]["us-gaap"]["LongTermDebtNoncurrent"] = _instant(400.0)
        from services.sec_company_facts_evidence import build_company_facts_evidence
        from services.sec_financial_client import SECFinancialClient

        evidence = build_company_facts_evidence(
            symbol="AAPL",
            cik="0000320193",
            raw_payload=payload,
            http_status=200,
        )
        extracted = SECFinancialClient(contact_email="cache-replay@localhost").extract_financials(
            evidence.raw_payload
        )
        snapshot = _snapshot("AAPL", "0000320193", PARTICIPATION_STATUS_UYGUN_DEGIL)
        snapshot["assessment_payload"]["financial_inputs"]["non_permissible_revenue"] = None
        item = assess_from_cached_evidence(
            identity=AssessedEquityIdentity(
                symbol="AAPL",
                cik="0000320193",
                cik_source="snapshot",
                fetchable=True,
            ),
            evidence=evidence,
            snapshot=snapshot,
            extracted=extracted,
        )
        self.assertNotEqual(item.new_status, PARTICIPATION_STATUS_UYGUN)


if __name__ == "__main__":
    unittest.main()
