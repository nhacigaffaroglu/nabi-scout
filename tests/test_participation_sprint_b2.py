from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from services.candidate_pipeline_presentation import is_actionable_opportunity
from services.global_participation_reconciliation import assess_from_cached_evidence
from services.participation_cached_evidence_resolver import (
    NPR_STATE_MISSING,
    resolve_business_npr_from_cached_company_facts,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.participation_pending_offline import (
    dry_run_cohort_from_cache,
    fetch_cohort_company_facts,
    plan_cohort_company_facts,
    preflight_named_cohort,
)
from services.research_eligibility_service import evaluate_research_eligibility_from_assessment
from services.sec_company_facts_evidence import build_company_facts_evidence, pad_cik
from services.sec_participation_evidence_population import AssessedEquityIdentity
from repositories.sec_company_facts_cache import SecCompanyFactsCache
from tests.test_global_participation_reconciliation import _business_pass, _snapshot
from tests.test_participation_cached_evidence_resolver import _facts_payload, _financials
from tests.test_sec_company_facts_cache import _facts

B2_IDENTITIES = {
    "ODFL": "0000878927",
    "ON": "0001097864",
    "PANW": "0001327567",
    "PAYX": "0000723531",
    "PCAR": "0000075362",
    "PYPL": "0001633917",
    "REGN": "0000872589",
    "ROST": "0000745732",
    "SNPS": "0000883241",
    "TEAM": "0001650372",
    "VRSK": "0001442145",
    "VRTX": "0000875320",
    "WBD": "0001437107",
    "WDAY": "0001327811",
    "XEL": "0000072903",
    "ZS": "0001713683",
}


def _queue(symbol: str, status: str) -> dict:
    return {"symbol": symbol, "status": status}


class B2IdentityTests(unittest.TestCase):
    def test_all_sixteen_identities_are_unique_and_padded(self) -> None:
        self.assertEqual(len(B2_IDENTITIES), 16)
        padded = [pad_cik(cik) for cik in B2_IDENTITIES.values()]
        self.assertEqual(len(set(padded)), 16)
        self.assertTrue(all(len(cik) == 10 and cik.isdigit() for cik in padded))

    def test_preflight_reports_pending_versus_processed_without_repair(self) -> None:
        symbols = ("ODFL", "REGN")
        preflight = preflight_named_cohort(
            symbols,
            queue_rows={
                "ODFL": _queue("ODFL", "PENDING"),
                "REGN": _queue("REGN", "COMPLETED"),
            },
            snapshots_by_symbol={"REGN": _snapshot("REGN", "872589", PARTICIPATION_STATUS_UYGUN_DEGIL)},
        )
        self.assertEqual(preflight.pending_confirmed, ("ODFL",))
        self.assertEqual(preflight.already_processed, ("REGN",))
        self.assertEqual(preflight.conflicts, ("ODFL",))
        odfl = preflight.identities[0]
        self.assertFalse(odfl.fetchable)
        self.assertIn("missing_cik", odfl.problems)

    def test_cik_conflict_is_not_silently_repaired(self) -> None:
        preflight = preflight_named_cohort(
            ("TEAM",),
            queue_rows={"TEAM": _queue("TEAM", "RETRYABLE")},
            snapshots_by_symbol={"TEAM": _snapshot("TEAM", "1650372", PARTICIPATION_STATUS_KONTROL_ET)},
            candidates_by_symbol={"TEAM": {"symbol": "TEAM", "cik": "1"}},
        )
        self.assertEqual(preflight.conflicts, ("TEAM",))
        self.assertFalse(preflight.identities[0].fetchable)
        self.assertIn("snapshot_candidate_cik_conflict", preflight.identities[0].problems)


class B2CanonicalAssessmentTests(unittest.TestCase):
    def test_cache_plan_and_dry_run_replay(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            symbol = "SNPS"
            snapshot = _snapshot(symbol, "883241", PARTICIPATION_STATUS_KONTROL_ET)
            snapshot["assessment_payload"]["financial_inputs"]["non_permissible_revenue"] = None
            snapshot["assessment_payload"]["business_screen_result"] = _business_pass(symbol)
            preflight = preflight_named_cohort(
                (symbol,),
                queue_rows={symbol: _queue(symbol, "RETRYABLE")},
                snapshots_by_symbol={symbol: snapshot},
            )
            plan = plan_cohort_company_facts(preflight, cache=cache)
            self.assertEqual(plan.expected_sec_calls, 1)
            self.assertEqual(plan.cache_misses, (symbol,))
            calls = {"n": 0}

            def fetcher(cik: str) -> dict:
                calls["n"] += 1
                return _facts(200)

            fetched = fetch_cohort_company_facts(plan, fetcher=fetcher, cache=cache)
            self.assertEqual(fetched.sec_calls, 1)
            self.assertEqual(calls["n"], 1)
            cache.verify_digest(cache.get_latest(symbol=symbol).content_digest)
            replayed = dry_run_cohort_from_cache(
                preflight,
                snapshots_by_symbol={symbol: snapshot},
                cache=cache,
            )
            self.assertEqual(replayed[0]["old_status"], PARTICIPATION_STATUS_KONTROL_ET)
            self.assertIsNotNone(replayed[0]["new_status"])
            self.assertEqual(replayed[0]["period"], "2025-12-31")

    def test_missing_npr_stays_none(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "TEAM",
            _facts_payload(),
            sec_financials=_financials(),
        )
        self.assertIsNone(result.npr_amount)
        self.assertEqual(result.npr_state, NPR_STATE_MISSING)

    def test_period_integrity_uses_financial_period_end(self) -> None:
        payload = _facts_payload(
            segments=(("Subscription", 100.0),),
            period="2024-12-31",
        )
        result = resolve_business_npr_from_cached_company_facts(
            "ON",
            payload,
            sec_financials=_financials(period="2025-12-31"),
        )
        self.assertEqual(result.period, "2025-12-31")
        self.assertEqual(result.business_evidence.revenue_segments, ())


class B2FirewallAndRegressionTests(unittest.TestCase):
    def test_kontrol_et_and_rejected_are_not_actionable(self) -> None:
        for status in (PARTICIPATION_STATUS_KONTROL_ET, PARTICIPATION_STATUS_UYGUN_DEGIL):
            self.assertFalse(
                is_actionable_opportunity(
                    {
                        "symbol": "REGN",
                        "participation_status": status,
                        "decision": "GÜÇLÜ ADAY",
                        "current_price": 10.0,
                        "data_completeness": 90,
                        "nabi_score": 80,
                        "last_scanned_at": "2026-08-01T00:00:00+00:00",
                        "research_status": "TAMAMLANDI",
                    }
                )
            )

    def test_approved_anchor_stays_uygun_when_snapshot_npr_proven(self) -> None:
        evidence = build_company_facts_evidence(
            symbol="CRM",
            cik="0001108524",
            raw_payload=_facts_payload(),
            http_status=200,
        )
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
        self.assertEqual(item.new_status, PARTICIPATION_STATUS_UYGUN)

    def test_rejected_financial_fail_is_not_converted_to_uygun(self) -> None:
        payload = _facts_payload()
        payload["facts"]["us-gaap"]["LongTermDebtNoncurrent"] = {
            "units": {
                "USD": [
                    {
                        "form": "10-K",
                        "end": "2025-12-31",
                        "val": 400.0,
                        "filed": "2026-02-17",
                    }
                ]
            }
        }
        evidence = build_company_facts_evidence(
            symbol="AAPL",
            cik="0000320193",
            raw_payload=payload,
            http_status=200,
        )
        from services.sec_financial_client import SECFinancialClient

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

    def test_b1_unresolved_missing_npr_stays_kontrol_et(self) -> None:
        result = resolve_business_npr_from_cached_company_facts(
            "NVDA",
            _facts_payload(),
            sec_financials=_financials(),
        )
        self.assertEqual(result.npr_state, NPR_STATE_MISSING)
        eligibility = evaluate_research_eligibility_from_assessment(None, symbol="NVDA")
        self.assertFalse(eligibility.research_allowed)


if __name__ == "__main__":
    unittest.main()
