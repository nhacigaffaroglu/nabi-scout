from __future__ import annotations

import unittest
from pathlib import Path

from repositories.universe_expansion_repository import UniverseExpansionRepository
from services.hybrid_exposure_allocation_policy import resolve_hybrid_allocation_policy
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.strategic_layer_discovery import (
    CLOSED_STRATEGIC_REIT_SYMBOLS,
    actionability_from_candidate,
    classification_from_evidence,
    discovery_hint_is_not_classification,
    evaluate_discovery_record,
    may_run_actionability,
    may_run_reit_economic_classification,
    plan_strategic_enqueue,
    select_us_listing_discovery_candidates,
    tickers_from_sec_sic_lookup,
)
from services.strategic_layer_discovery_contract import (
    ACTIONABILITY_FAIL,
    ACTIONABILITY_NOT_RUN,
    ACTIONABILITY_PASS,
    CLASSIFICATION_FAIL,
    CLASSIFICATION_PASS,
    CLASSIFICATION_UNKNOWN,
    GATE_BLOCKED,
    GATE_ELIGIBLE,
    PARTICIPATION_NOT_RUN,
    REASON_ROBUST_UW_SUKUK,
    StrategicDiscoveryRecord,
    three_gate_eligibility,
)
from services.sukuk_evidence_contract import classify_from_name_or_fund
from services.universe_expansion_contract import EXPANSION_STATUS_PENDING
from services.universe_listing_identity import STRATEGIC_LAYER_DISCOVERY_SOURCE


CONTRACT = Path("services/strategic_layer_discovery_contract.py")
SERVICE = Path("services/strategic_layer_discovery.py")


def _row(**kwargs) -> StrategicDiscoveryRecord:
    payload = dict(
        symbol="X",
        name="Example",
        instrument_identity="ETF",
        exchange="NYSE",
        country="US",
        provider_identifiers={},
        economic_layer_candidate="sukuk",
        classification_evidence="",
        classification_status=CLASSIFICATION_PASS,
        participation_status=PARTICIPATION_STATUS_UYGUN,
        research_allowed=True,
        actionability=ACTIONABILITY_PASS,
        discovery_reason=REASON_ROBUST_UW_SUKUK,
    )
    payload.update(kwargs)
    return StrategicDiscoveryRecord(**payload)


class ContractTests(unittest.TestCase):
    def test_discovery_reason_is_not_classification_evidence(self) -> None:
        self.assertEqual(
            classification_from_evidence(
                target_layer="sukuk",
                security_name="Global Sukuk Income Fund",
                fund_symbol="SPSK",
            ),
            CLASSIFICATION_UNKNOWN,
        )
        self.assertEqual(classify_from_name_or_fund("SP Funds Sukuk ETF", "SPSK"), "UNKNOWN")
        self.assertEqual(
            three_gate_eligibility(
                classification_status=CLASSIFICATION_UNKNOWN,
                participation_status=PARTICIPATION_STATUS_UYGUN,
                actionability=ACTIONABILITY_PASS,
                discovery_reason=REASON_ROBUST_UW_SUKUK,
            ),
            GATE_BLOCKED,
        )
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("must never authorize", text)

    def test_name_and_mandate_rejected(self) -> None:
        self.assertEqual(
            classification_from_evidence(
                target_layer="real_estate",
                security_name="Realty Income REIT",
                fund_symbol="SPRE",
            ),
            CLASSIFICATION_UNKNOWN,
        )
        self.assertEqual(
            classification_from_evidence(
                target_layer="sukuk",
                explicit_layer="fixed_income",
            ),
            CLASSIFICATION_FAIL,
        )
        self.assertEqual(
            classification_from_evidence(
                target_layer="real_estate",
                explicit_layer="real_estate",
            ),
            CLASSIFICATION_PASS,
        )

    def test_economic_classification_independent_of_participation(self) -> None:
        row = _row(
            classification_status=CLASSIFICATION_PASS,
            participation_status=PARTICIPATION_NOT_RUN,
            actionability=ACTIONABILITY_PASS,
        )
        self.assertEqual(evaluate_discovery_record(row), GATE_BLOCKED)
        self.assertEqual(row.classification_status, CLASSIFICATION_PASS)

    def test_three_gate_eligibility(self) -> None:
        self.assertEqual(
            three_gate_eligibility(
                classification_status=CLASSIFICATION_PASS,
                participation_status=PARTICIPATION_STATUS_UYGUN,
                actionability=ACTIONABILITY_PASS,
            ),
            GATE_ELIGIBLE,
        )

    def test_kontrol_et_uygun_degil_missing_and_actionability_blocked(self) -> None:
        for status in (
            PARTICIPATION_STATUS_KONTROL_ET,
            PARTICIPATION_STATUS_UYGUN_DEGIL,
            PARTICIPATION_NOT_RUN,
            "",
        ):
            self.assertEqual(
                three_gate_eligibility(
                    classification_status=CLASSIFICATION_PASS,
                    participation_status=status,
                    actionability=ACTIONABILITY_PASS,
                ),
                GATE_BLOCKED,
            )
        self.assertEqual(
            three_gate_eligibility(
                classification_status=CLASSIFICATION_PASS,
                participation_status=PARTICIPATION_STATUS_UYGUN,
                actionability=ACTIONABILITY_FAIL,
            ),
            GATE_BLOCKED,
        )
        self.assertEqual(
            three_gate_eligibility(
                classification_status=CLASSIFICATION_PASS,
                participation_status=PARTICIPATION_STATUS_UYGUN,
                actionability=ACTIONABILITY_NOT_RUN,
            ),
            GATE_BLOCKED,
        )

    def test_queue_cannot_directly_authorize(self) -> None:
        repo = UniverseExpansionRepository()
        plan = plan_strategic_enqueue(["WELL"], repo=repo, dry_run=False)
        self.assertEqual(plan.inserted, 1)
        row = repo.get_by_symbol("WELL")
        self.assertEqual(row["status"], EXPANSION_STATUS_PENDING)
        self.assertEqual(row["source_universe"], STRATEGIC_LAYER_DISCOVERY_SOURCE)
        self.assertFalse(row.get("participation_status"))
        self.assertNotEqual(row.get("participation_status"), PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(
            actionability_from_candidate(
                {
                    **row,
                    "decision": "GÜÇLÜ ADAY",
                    "current_price": 10,
                    "nabi_score": 95,
                }
            ),
            ACTIONABILITY_FAIL,
        )

    def test_etf_not_enqueued_on_equity_queue(self) -> None:
        repo = UniverseExpansionRepository()
        plan = plan_strategic_enqueue(
            ["SPSK", "SPRE", "SKUK"],
            repo=repo,
            names={"SPSK": "SP Funds Dow Jones Global Sukuk ETF"},
            dry_run=False,
        )
        self.assertEqual(plan.inserted, 1)
        self.assertGreaterEqual(plan.skipped_etf, 1)
        self.assertIsNone(repo.get_by_symbol("SPSK"))
        self.assertIsNone(repo.get_by_symbol("SPRE"))
        self.assertEqual(repo.get_by_symbol("SKUK")["status"], EXPANSION_STATUS_PENDING)

    def test_dry_run_writes_nothing(self) -> None:
        repo = UniverseExpansionRepository()
        plan = plan_strategic_enqueue(["O"], repo=repo, dry_run=True)
        self.assertTrue(plan.dry_run)
        self.assertEqual(plan.proposed_insert, 1)
        self.assertEqual(plan.inserted, 0)
        self.assertEqual(plan.write_tables, ())
        self.assertIsNone(repo.get_by_symbol("O"))

    def test_research_allowed_false_blocked(self) -> None:
        self.assertEqual(
            three_gate_eligibility(
                classification_status=CLASSIFICATION_PASS,
                participation_status=PARTICIPATION_STATUS_UYGUN,
                actionability=ACTIONABILITY_NOT_RUN,
            ),
            GATE_BLOCKED,
        )
        self.assertEqual(
            evaluate_discovery_record(
                _row(
                    research_allowed=False,
                    participation_status=PARTICIPATION_STATUS_KONTROL_ET,
                    actionability=ACTIONABILITY_NOT_RUN,
                )
            ),
            GATE_BLOCKED,
        )

    def test_hybrid_remains_off(self) -> None:
        self.assertFalse(resolve_hybrid_allocation_policy().enabled)
        self.assertNotIn("enable_hybrid", SERVICE.read_text(encoding="utf-8"))

    def test_discovery_hint_is_not_classification(self) -> None:
        self.assertEqual(
            discovery_hint_is_not_classification("SPRE constituent / Real Estate"),
            CLASSIFICATION_UNKNOWN,
        )
        self.assertEqual(
            classification_from_evidence(
                target_layer="real_estate",
                fund_symbol="SPRE",
                security_name="EastGroup Properties REIT",
            ),
            CLASSIFICATION_UNKNOWN,
        )

    def test_participation_first_only_uygun_reaches_reit_evidence(self) -> None:
        self.assertTrue(may_run_reit_economic_classification(participation_status="Uygun"))
        self.assertFalse(
            may_run_reit_economic_classification(participation_status=PARTICIPATION_STATUS_KONTROL_ET)
        )
        self.assertFalse(
            may_run_reit_economic_classification(participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        self.assertFalse(may_run_reit_economic_classification(participation_status=""))

    def test_uygun_degil_and_kontrol_et_stop_downstream_classification(self) -> None:
        self.assertFalse(
            may_run_reit_economic_classification(participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL)
        )
        self.assertFalse(
            may_run_actionability(
                participation_status=PARTICIPATION_STATUS_UYGUN_DEGIL,
                classification_status=CLASSIFICATION_PASS,
            )
        )
        self.assertFalse(
            may_run_actionability(
                participation_status=PARTICIPATION_STATUS_KONTROL_ET,
                classification_status=CLASSIFICATION_PASS,
            )
        )
        self.assertFalse(
            may_run_actionability(
                participation_status=PARTICIPATION_STATUS_UYGUN,
                classification_status=CLASSIFICATION_FAIL,
            )
        )
        self.assertTrue(
            may_run_actionability(
                participation_status=PARTICIPATION_STATUS_UYGUN,
                classification_status=CLASSIFICATION_PASS,
            )
        )

    def test_select_skips_closed_and_requires_us_listing_cik(self) -> None:
        listing = {
            "EGP": {
                "instrument_type": "EQUITY",
                "source": "us_listing",
                "cik": "0049002",
                "exchange": "NYSE",
            },
            "PLD": {
                "instrument_type": "EQUITY",
                "source": "us_listing",
                "cik": "1045609",
                "exchange": "NYSE",
            },
            "GMG": {"instrument_type": "UNKNOWN", "source": "", "cik": ""},
            "SUI": {
                "instrument_type": "EQUITY",
                "source": "us_listing",
                "cik": "",
                "exchange": "NYSE",
            },
        }
        selected = select_us_listing_discovery_candidates(
            ["EGP", "PLD", "GMG", "SUI", "EGP"],
            listing_rows=listing,
            queued_symbols=(),
        )
        self.assertEqual([row["symbol"] for row in selected], ["EGP"])
        self.assertIsNone(selected[0]["economic_layer"])
        self.assertEqual(selected[0]["classification_status"], CLASSIFICATION_UNKNOWN)
        self.assertIn("PLD", CLOSED_STRATEGIC_REIT_SYMBOLS)

    def test_sec_sic_join_is_discovery_hint_not_classification(self) -> None:
        tickers = tickers_from_sec_sic_lookup(
            ["0001045609", 49002],
            {
                "PLD": {"cik": "1045609"},
                "EGP": {"cik": "0049002"},
                "AAPL": {"cik": "320193"},
            },
        )
        self.assertEqual(set(tickers), {"PLD", "EGP"})
        self.assertEqual(discovery_hint_is_not_classification("SIC:6798"), CLASSIFICATION_UNKNOWN)
