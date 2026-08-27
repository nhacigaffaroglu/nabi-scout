from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from repositories.sec_company_facts_cache import SecCompanyFactsCache
from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.global_participation_reconciliation import (
    apply_global_participation_reconciliation,
    assess_from_cached_evidence,
    plan_global_participation_reconciliation,
)
from services.participation_assessment_persistence_service import build_snapshot_payload
from services.participation_business_contract import (
    EVIDENCE_COMPLETENESS_COMPLETE,
    BusinessActivityRuleResult,
    BusinessActivityScreenResult,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_INSUFFICIENT_DATA,
    RULE_OUTCOME_PASS,
)
from services.sec_financial_client import (
    SEC_FINANCIAL_EXTRACTOR_VERSION,
    SECFinancialClient,
)
from services.sec_participation_evidence_population import AssessedEquityIdentity
from services.universe_expansion_contract import (
    EXPANSION_STATUS_COMPLETED,
    EXPANSION_STATUS_PENDING,
    EXPANSION_STATUS_RETRYABLE,
)


END = "2025-12-31"
FILED = "2026-02-17"


def _instant(val: float) -> dict[str, Any]:
    return {
        "units": {
            "USD": [
                {
                    "form": "10-K",
                    "end": END,
                    "val": val,
                    "filed": FILED,
                }
            ]
        }
    }


def _duration(val: float) -> dict[str, Any]:
    return {
        "units": {
            "USD": [
                {
                    "form": "10-K",
                    "start": "2025-01-01",
                    "end": END,
                    "val": val,
                    "filed": FILED,
                }
            ]
        }
    }


def _company_facts(**facts: Any) -> dict[str, Any]:
    return {"facts": {"us-gaap": facts}}


def _business_pass(symbol: str) -> dict[str, Any]:
    return BusinessActivityScreenResult(
        symbol=symbol,
        methodology_id="msci_islamic_index_series",
        methodology_version="2025-05",
        rule_results=(
            BusinessActivityRuleResult(
                rule_id="msci.sic_exclusions",
                category="sic",
                outcome=RULE_OUTCOME_PASS,
            ),
            BusinessActivityRuleResult(
                rule_id="msci.sector_exclusions",
                category="sector",
                outcome=RULE_OUTCOME_PASS,
            ),
            BusinessActivityRuleResult(
                rule_id="msci.description_keywords",
                category="keyword",
                outcome=RULE_OUTCOME_INSUFFICIENT_DATA,
            ),
            BusinessActivityRuleResult(
                rule_id="msci.non_permissible_revenue",
                category="revenue",
                outcome=RULE_OUTCOME_PASS,
                ratio_pct=0.0,
                threshold_pct=5.0,
                comparator="<=",
            ),
        ),
        overall_outcome=RULE_OUTCOME_PASS,
        evidence_completeness=EVIDENCE_COMPLETENESS_COMPLETE,
        business_rules_evaluated=True,
        methodology_complete=True,
    ).to_dict()


def _snapshot(
    symbol: str,
    cik: str,
    status: str,
    *,
    total_debt: Optional[float] = 1.0,
    total_assets: float = 100.0,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "status": status,
        "source_evidence": {"cik": cik, "provider": "SEC"},
        "assessment_payload": {
            "screening_context": "NEW_ENTRY",
            "source_evidence": {"cik": cik, "provider": "SEC"},
            "financial_inputs": {
                "total_debt": total_debt,
                "total_assets": total_assets,
                "non_permissible_revenue": 0.0,
            },
            "business_screen_result": _business_pass(symbol),
        },
    }


class FakeParticipationRepo:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def append_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        row = {"id": f"snap-{len(self.rows) + 1}", **payload}
        self.rows.append(row)
        return row

    def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        matches = [
            row
            for row in self.rows
            if str(row.get("symbol") or "").upper() == symbol.upper()
        ]
        return matches[-1] if matches else None


class FakeCandidateRepo:
    def __init__(self) -> None:
        self.updates: List[tuple[str, Dict[str, Any]]] = []

    def update(self, candidate_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.updates.append((candidate_id, dict(payload)))
        return {"id": candidate_id, **payload}


def _hon_facts() -> dict[str, Any]:
    return _company_facts(
        Revenues=_duration(37_442_000_000),
        Assets=_instant(73_681_000_000),
        CashAndCashEquivalentsAtCarryingValue=_instant(12_487_000_000),
        AccountsReceivableNetCurrent=_instant(7_621_000_000),
        AvailableForSaleSecuritiesDebtSecurities=_instant(531_000_000),
        ShortTermInvestments=_instant(443_000_000),
        DebtLongtermAndShorttermCombinedAmount=_instant(28_687_000_000),
        LongTermDebtAndCapitalLeaseObligations=_instant(27_141_000_000),
        LongTermDebtAndCapitalLeaseObligationsCurrent=_instant(1_546_000_000),
        ShortTermBorrowings=_instant(5_893_000_000),
    )


class HonForensicFixtureTests(unittest.TestCase):
    def test_hon_combined_debt_fails_existing_msci_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            evidence, _created = cache.store_if_new(
                symbol="HON",
                cik="773840",
                raw_payload=_hon_facts(),
            )
            extracted = cache.replay(evidence)
            self.assertEqual(extracted["total_debt"], 28_687_000_000)
            self.assertEqual(
                extracted["total_debt_tags"],
                "DebtLongtermAndShorttermCombinedAmount",
            )
            self.assertEqual(extracted["total_assets"], 73_681_000_000)
            item = assess_from_cached_evidence(
                identity=AssessedEquityIdentity(
                    symbol="HON",
                    cik="0000773840",
                    cik_source="snapshot",
                    fetchable=True,
                ),
                evidence=evidence,
                snapshot=_snapshot(
                    "HON",
                    "773840",
                    PARTICIPATION_STATUS_UYGUN,
                    total_debt=5_893_000_000,
                    total_assets=73_681_000_000,
                ),
                extracted=extracted,
            )
            self.assertEqual(item.old_status, PARTICIPATION_STATUS_UYGUN)
            self.assertEqual(item.new_status, PARTICIPATION_STATUS_UYGUN_DEGIL)
            debt_rule = next(
                rule
                for rule in item.result.financial_screen_result.rule_results
                if rule.rule_id == "msci.total_debt_to_total_assets"
            )
            self.assertAlmostEqual(debt_rule.ratio_pct, 38.934, places=3)
            self.assertEqual(debt_rule.threshold_pct, 30.0)
            self.assertNotIn(
                "ShortTermBorrowings",
                extracted.get("total_debt_tags") or "",
            )


class GlobalReconcileTests(unittest.TestCase):
    def _pass_facts(self, assets: float = 100.0, debt: float = 10.0) -> dict[str, Any]:
        return _company_facts(
            Revenues=_duration(80.0),
            Assets=_instant(assets),
            CashAndCashEquivalentsAtCarryingValue=_instant(5.0),
            AccountsReceivableNetCurrent=_instant(4.0),
            MarketableSecuritiesCurrent=_instant(1.0),
            MarketableSecuritiesNoncurrent=_instant(1.0),
            LongTermDebt=_instant(debt),
        )

    def test_apply_is_append_only_and_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            cache.store_if_new(symbol="AAA", cik="1", raw_payload=self._pass_facts())
            queue = [{"symbol": "AAA", "status": EXPANSION_STATUS_RETRYABLE, "id": "q1"}]
            snapshots = {
                "AAA": _snapshot("AAA", "1", PARTICIPATION_STATUS_KONTROL_ET),
            }
            plan = plan_global_participation_reconciliation(
                queue_rows=queue,
                snapshots_by_symbol=snapshots,
                cache=cache,
            )
            self.assertEqual(len(plan.items), 1)
            self.assertEqual(plan.items[0].new_status, PARTICIPATION_STATUS_UYGUN)
            repo = FakeParticipationRepo()
            candidates = FakeCandidateRepo()
            queue_repo = UniverseExpansionRepository()
            row = queue_repo.upsert_pending("AAA", source_universe="test", priority=1)
            queue_repo.finalize(row["id"], {"status": EXPANSION_STATUS_RETRYABLE})
            row = queue_repo.get_by_symbol("AAA")
            plan_queue = [row]
            first = apply_global_participation_reconciliation(
                plan,
                participation_repo=repo,
                candidate_repo=candidates,
                queue_repo=queue_repo,
                candidates_by_symbol={
                    "AAA": {"id": "c1", "participation_status": PARTICIPATION_STATUS_KONTROL_ET}
                },
                queue_rows=plan_queue,
            )
            self.assertEqual(first.created, ["AAA"])
            self.assertEqual(len(repo.rows), 1)
            self.assertEqual(candidates.updates, [("c1", {"participation_status": PARTICIPATION_STATUS_UYGUN})])
            self.assertEqual(queue_repo.get_by_symbol("AAA")["status"], EXPANSION_STATUS_COMPLETED)
            second = apply_global_participation_reconciliation(
                plan,
                participation_repo=repo,
                candidate_repo=candidates,
                queue_repo=queue_repo,
                candidates_by_symbol={
                    "AAA": {"id": "c1", "participation_status": PARTICIPATION_STATUS_UYGUN}
                },
                queue_rows=[queue_repo.get_by_symbol("AAA")],
            )
            self.assertEqual(second.created, [])
            self.assertEqual(second.reused, ["AAA"])
            self.assertEqual(len(repo.rows), 1)
            self.assertEqual(len(candidates.updates), 1)

    def test_uygun_degil_is_queue_terminal(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            cache.store_if_new(
                symbol="BBB",
                cik="2",
                raw_payload=self._pass_facts(assets=100.0, debt=50.0),
            )
            snapshots = {
                "BBB": _snapshot("BBB", "2", PARTICIPATION_STATUS_KONTROL_ET),
            }
            plan = plan_global_participation_reconciliation(
                queue_rows=[{"symbol": "BBB", "status": EXPANSION_STATUS_RETRYABLE}],
                snapshots_by_symbol=snapshots,
                cache=cache,
            )
            self.assertEqual(plan.items[0].new_status, PARTICIPATION_STATUS_UYGUN_DEGIL)
            self.assertEqual(plan.items[0].queue_status, EXPANSION_STATUS_COMPLETED)
            queue_repo = UniverseExpansionRepository()
            queued = queue_repo.upsert_pending("BBB", source_universe="test", priority=1)
            queue_repo.finalize(queued["id"], {"status": EXPANSION_STATUS_RETRYABLE})
            queued = queue_repo.get_by_symbol("BBB")
            apply_global_participation_reconciliation(
                plan,
                participation_repo=FakeParticipationRepo(),
                queue_repo=queue_repo,
                queue_rows=[queued],
            )
            updated = queue_repo.get_by_symbol("BBB")
            self.assertEqual(updated["status"], EXPANSION_STATUS_COMPLETED)
            self.assertEqual(updated["participation_status"], PARTICIPATION_STATUS_UYGUN_DEGIL)
            self.assertFalse(updated["research_allowed"])

    def test_kontrol_et_is_queue_terminal_and_pending_is_untouched(self) -> None:
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            incomplete = _company_facts(
                Revenues=_duration(80.0),
                Assets=_instant(100.0),
                CashAndCashEquivalentsAtCarryingValue=_instant(5.0),
            )
            cache.store_if_new(symbol="CCC", cik="3", raw_payload=incomplete)
            snapshots = {
                "CCC": _snapshot("CCC", "3", PARTICIPATION_STATUS_KONTROL_ET),
            }
            plan = plan_global_participation_reconciliation(
                queue_rows=[
                    {"symbol": "CCC", "status": EXPANSION_STATUS_RETRYABLE},
                    {"symbol": "PEND", "status": EXPANSION_STATUS_PENDING},
                ],
                snapshots_by_symbol=snapshots,
                cache=cache,
            )
            self.assertEqual([item.symbol for item in plan.items], ["CCC"])
            self.assertEqual(plan.items[0].new_status, PARTICIPATION_STATUS_KONTROL_ET)
            self.assertEqual(plan.items[0].queue_status, EXPANSION_STATUS_COMPLETED)
            queue_repo = UniverseExpansionRepository()
            ccc = queue_repo.upsert_pending("CCC", source_universe="test", priority=1)
            queue_repo.finalize(ccc["id"], {"status": EXPANSION_STATUS_RETRYABLE})
            ccc = queue_repo.get_by_symbol("CCC")
            pending = queue_repo.upsert_pending("PEND", source_universe="test", priority=2)
            apply_global_participation_reconciliation(
                plan,
                participation_repo=FakeParticipationRepo(),
                queue_repo=queue_repo,
                queue_rows=[ccc, pending],
            )
            updated = queue_repo.get_by_symbol("CCC")
            self.assertEqual(updated["status"], EXPANSION_STATUS_COMPLETED)
            self.assertEqual(updated["participation_status"], PARTICIPATION_STATUS_KONTROL_ET)
            self.assertFalse(updated["research_allowed"])
            self.assertIsNone(updated["last_error_category"])
            self.assertIsNone(updated["next_retry_at"])
            self.assertEqual(queue_repo.get_by_symbol("PEND")["status"], EXPANSION_STATUS_PENDING)

    def test_candidate_sync_writes_participation_status_only(self) -> None:
        repo = FakeCandidateRepo()
        with TemporaryDirectory() as tmp:
            cache = SecCompanyFactsCache(root=Path(tmp))
            cache.store_if_new(symbol="DDD", cik="4", raw_payload=self._pass_facts())
            plan = plan_global_participation_reconciliation(
                queue_rows=[{"symbol": "DDD", "status": EXPANSION_STATUS_COMPLETED}],
                snapshots_by_symbol={
                    "DDD": _snapshot("DDD", "4", PARTICIPATION_STATUS_KONTROL_ET)
                },
                cache=cache,
            )
            apply_global_participation_reconciliation(
                plan,
                participation_repo=FakeParticipationRepo(),
                candidate_repo=repo,
                candidates_by_symbol={
                    "DDD": {
                        "id": "cand-1",
                        "participation_status": PARTICIPATION_STATUS_KONTROL_ET,
                        "nabi_score": 88,
                        "decision": "ARAŞTIR",
                    }
                },
            )
            self.assertEqual(len(repo.updates), 1)
            self.assertEqual(set(repo.updates[0][1].keys()), {"participation_status"})

    def test_script_has_no_hardcoded_symbol_allowlist(self) -> None:
        source = Path("scripts/reconcile_global_participation.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("EXPECTED_TRANSITIONS", source)
        self.assertNotIn("ADSK", source)
        self.assertNotIn("HON", source)
        self.assertIn("--apply", source)

    def test_reconcile_module_does_not_call_providers(self) -> None:
        import services.global_participation_reconciliation as module

        source = inspect.getsource(module)
        for token in (
            "fmp_client",
            "company_facts(",
            "scanner_v",
            "nabi_score_v4",
            "openai",
            "anthropic",
        ):
            self.assertNotIn(token, source)
        self.assertEqual(SEC_FINANCIAL_EXTRACTOR_VERSION, "us-gaap-period-aligned-exclusive-debt-v3")


if __name__ == "__main__":
    unittest.main()
