from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from services.fund_product_contract import (
    FUND_EVAL_ENGINE_VERSION,
    FUND_EVAL_FACTS_VERSION,
    LAYER_CASH_LIKE,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION,
    PILOT_FUND_SYMBOLS,
    REGION_TR,
)
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import DECISION_WATCH
from services.security_intelligence_contract import FRESHNESS_STALE
from services.turkiye_fund_persistence import (
    MemoryParticipationAssessmentRepository,
    MemorySecurityIntelligenceSnapshotRepository,
)
from services.turkiye_fund_snapshot_reader import (
    FI_SELECTION_RULE,
    PARTICIPATION_SELECTION_RULE,
    REASON_AIS_CASH_FIREWALL,
    REASON_FI_MISSING,
    REASON_INCOMPATIBLE_FI_VERSION,
    REASON_INCOMPATIBLE_METHODOLOGY,
    REASON_PARTICIPATION_MISSING,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_RESEARCH_NOT_ALLOWED,
    REASON_STALE_FI,
    REASON_WRITE_BLOCKED,
    ReadOnlyRepository,
    SnapshotReadError,
    evaluate_snapshot_fund_decision,
    read_fund_intelligence_snapshot,
    read_participation_snapshot,
    read_pilot_canonical,
    read_turkiye_fund_canonical,
)
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_turkiye_fund_8e import FROZEN_FI

READER = Path("services/turkiye_fund_snapshot_reader.py")
ORCHESTRATOR = Path("services/turkiye_fund_refresh_orchestrator.py")
BIST = Path("services/bist_refresh_contract.py")
BIST_ORCH = Path("services/bist_refresh_orchestrator.py")
US_SI = Path("services/security_intelligence_engine.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")

ACCEPTED_PARTICIPATION_IDS = {
    "AIS": "8e9a0c03-ece7-40a1-9c04-98a2baf49350",
    "ZPE": "4a15e61d-a9cb-49a7-aa79-dd78ee554f83",
    "IAT": "0b9f2308-4ee8-4ab6-9136-11c4b26fcee9",
}
ACCEPTED_FI_IDS = {
    "AIS": "cbbd654c-a71b-422e-a325-c20782792e7b",
    "ZPE": "90ad219d-cbdc-4b21-9319-11a9d11b58a6",
    "IAT": "1ffe1489-1bdb-4f95-a7a1-0a43e31d4cec",
}
ACCEPTED_SEMANTIC = {
    "AIS": "acfcf0c4b20893d9ba4104f7c9db5e82494dec014ace247e10b9314f3d662c92",
    "ZPE": "f971ca43d0c7a5a0d0434019556091d46ff2fd60d13068cb7069481045bdf7aa",
    "IAT": "e9045bdbda4e71e57195691beaf5cd2767924316cc2a0a489da978ffa08db59e",
}
FROZEN_EXPOSURE = {
    "AIS": (LAYER_CASH_LIKE, REGION_TR, "MEDIUM"),
    "ZPE": ("equity", REGION_TR, "MEDIUM"),
    "IAT": ("sukuk", REGION_TR, "MEDIUM"),
}


def _part_row(symbol: str, **overrides) -> dict:
    layer, geo, conf = FROZEN_EXPOSURE[symbol]
    row = {
        "id": ACCEPTED_PARTICIPATION_IDS[symbol],
        "symbol": symbol,
        "assessed_at": "2026-08-31T05:22:29+00:00",
        "methodology_id": METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
        "methodology_version": METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION,
        "status": PARTICIPATION_STATUS_UYGUN,
        "source": "kap_izahname_pdr",
        "research_allowed": True,
        "semantic_identity": ACCEPTED_SEMANTIC[symbol],
        "source_evidence": {
            "source_as_of": {
                "kap_mandate": "2026-02-27" if symbol == "IAT" else "2026-01-13",
                "date_model": {
                    "kap_mandate": {
                        "value": "2026-02-27" if symbol == "IAT" else "2026-01-13",
                        "semantic": "PUBLISHED_AT",
                    }
                },
            }
        },
        "assessment_payload": {
            "instrument": "FUND",
            "market": "TR",
            "fund_code": symbol,
            "research_allowed": True,
            "participation_status": PARTICIPATION_STATUS_UYGUN,
            "blockers": [],
        },
    }
    row.update(overrides)
    return row


def _fi_row(symbol: str, **overrides) -> dict:
    score, state = FROZEN_FI[symbol]
    layer, geo, conf = FROZEN_EXPOSURE[symbol]
    mandate = "2026-02-27" if symbol == "IAT" else "2026-01-13"
    row = {
        "id": ACCEPTED_FI_IDS[symbol],
        "symbol": symbol,
        "as_of": "2026-08-28T00:00:00+00:00",
        "as_of_key": "2026-08-28",
        "facts_version": FUND_EVAL_FACTS_VERSION,
        "engine_version": FUND_EVAL_ENGINE_VERSION,
        "overall_score": score,
        "overall_status": state,
        "overall_confidence": 1.0,
        "investment_state": state,
        "participation_status": PARTICIPATION_STATUS_UYGUN,
        "research_allowed": True,
        "dimension_scores": {"performance_momentum": score},
        "dimension_statuses": {"performance_momentum": "READY"},
        "data_quality": {
            "market": "TR",
            "instrument": "FUND",
            "completeness": 1.0,
            "si_data_quality": "FUND",
            "source_as_of": {
                "tefas_price": "2026-08-28",
                "kap_mandate": mandate,
                "date_model": {
                    "kap_mandate": {"value": mandate, "semantic": "PUBLISHED_AT"}
                },
            },
            "economic_exposure": {
                "primary_exposure": layer,
                "geography": geo,
                "confidence": conf,
                "lookthrough_weights": [],
            },
            "unit_price": {"AIS": 0.108262, "ZPE": 36.063247, "IAT": 0.197873}[symbol],
            "unit_price_currency": "TRY",
            "unit_price_as_of": "2026-08-28",
            "unit_price_source": "TEFAS",
        },
        "reason_codes": [],
        "risk_flags": [],
        "change_flags": [],
    }
    row.update(overrides)
    return row


def _seeded_repos():
    part = MemoryParticipationAssessmentRepository()
    fi = MemorySecurityIntelligenceSnapshotRepository()
    for code in ("AIS", "ZPE", "IAT"):
        part.rows.append(_part_row(code))
        fi.rows.append(_fi_row(code))
    return part, fi


class TurkiyeFundSnapshotReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.part_repo, self.fi_repo = _seeded_repos()

    def test_hydrates_accepted_production_identities(self) -> None:
        for code, (score, state) in FROZEN_FI.items():
            part = read_participation_snapshot(self.part_repo, code)
            fi = read_fund_intelligence_snapshot(self.fi_repo, code)
            self.assertEqual(part.row_id, ACCEPTED_PARTICIPATION_IDS[code])
            self.assertEqual(part.status, PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(part.research_allowed)
            self.assertEqual(part.semantic_identity, ACCEPTED_SEMANTIC[code])
            self.assertEqual(part.methodology_id, METHODOLOGY_TURKIYE_FUND_PARTICIPATION)
            self.assertEqual(fi.row_id, ACCEPTED_FI_IDS[code])
            self.assertEqual(fi.score, score)
            self.assertEqual(fi.state, state)
            self.assertEqual(fi.completeness, 1.0)
            self.assertEqual(fi.confidence, 1.0)
            self.assertEqual(fi.facts_version, FUND_EVAL_FACTS_VERSION)
            self.assertEqual(fi.engine_version, FUND_EVAL_ENGINE_VERSION)
            layer, geo, conf = FROZEN_EXPOSURE[code]
            self.assertEqual(fi.exposure.primary_exposure, layer)
            self.assertEqual(fi.exposure.geography, geo)
            self.assertEqual(fi.exposure.confidence, conf)
            self.assertTrue(fi.snapshot.dimension_scores)

    def test_ais_cash_like_never_maps_to_portfolio_cash(self) -> None:
        fi = read_fund_intelligence_snapshot(self.fi_repo, "AIS")
        self.assertEqual(fi.exposure.primary_exposure, LAYER_CASH_LIKE)
        self.assertNotEqual(fi.exposure.primary_exposure, "cash")
        self.assertNotIn(fi.exposure.primary_exposure, {"cash", "CASH", "ASSET_CLASS_CASH"})
        cash = MemorySecurityIntelligenceSnapshotRepository()
        cash.rows.append(
            _fi_row(
                "AIS",
                data_quality={
                    "completeness": 1.0,
                    "economic_exposure": {"primary_exposure": "cash", "geography": "TR"},
                },
            )
        )
        with self.assertRaises(SnapshotReadError) as raised:
            read_fund_intelligence_snapshot(cash, "AIS")
        self.assertEqual(raised.exception.reason, REASON_AIS_CASH_FIREWALL)

    def test_applicability_skips_incompatible_newer_rows(self) -> None:
        self.part_repo.rows.append(
            _part_row(
                "AIS",
                id="newer-wrong-method",
                assessed_at="2026-08-31T06:00:00+00:00",
                methodology_id="equity_participation",
                methodology_version="other",
            )
        )
        self.fi_repo.rows.append(
            _fi_row(
                "AIS",
                id="newer-wrong-engine",
                as_of="2026-08-29T00:00:00+00:00",
                as_of_key="2026-08-29",
                engine_version="security_intelligence_8b.1",
                facts_version="security_facts_8c.1",
            )
        )
        part = read_participation_snapshot(self.part_repo, "AIS")
        fi = read_fund_intelligence_snapshot(self.fi_repo, "AIS")
        self.assertEqual(part.row_id, ACCEPTED_PARTICIPATION_IDS["AIS"])
        self.assertEqual(fi.row_id, ACCEPTED_FI_IDS["AIS"])
        self.assertIn("methodology_id", PARTICIPATION_SELECTION_RULE)
        self.assertIn("facts_version", FI_SELECTION_RULE)

    def test_incompatible_only_rows_fail_closed(self) -> None:
        part = MemoryParticipationAssessmentRepository()
        part.rows.append(_part_row("ZPE", methodology_id="equity_participation"))
        with self.assertRaises(SnapshotReadError) as raised:
            read_participation_snapshot(part, "ZPE")
        self.assertEqual(raised.exception.reason, REASON_INCOMPATIBLE_METHODOLOGY)
        fi = MemorySecurityIntelligenceSnapshotRepository()
        fi.rows.append(_fi_row("ZPE", engine_version="other"))
        with self.assertRaises(SnapshotReadError) as raised:
            read_fund_intelligence_snapshot(fi, "ZPE")
        self.assertEqual(raised.exception.reason, REASON_INCOMPATIBLE_FI_VERSION)

    def test_missing_and_stale_fail_closed(self) -> None:
        empty_part = MemoryParticipationAssessmentRepository()
        empty_fi = MemorySecurityIntelligenceSnapshotRepository()
        with self.assertRaises(SnapshotReadError) as raised:
            read_participation_snapshot(empty_part, "AIS")
        self.assertEqual(raised.exception.reason, REASON_PARTICIPATION_MISSING)
        with self.assertRaises(SnapshotReadError) as raised:
            read_fund_intelligence_snapshot(empty_fi, "AIS")
        self.assertEqual(raised.exception.reason, REASON_FI_MISSING)
        stale = MemorySecurityIntelligenceSnapshotRepository()
        stale.rows.append(_fi_row("IAT", reason_codes=[FRESHNESS_STALE]))
        with self.assertRaises(SnapshotReadError) as raised:
            read_fund_intelligence_snapshot(stale, "IAT")
        self.assertEqual(raised.exception.reason, REASON_STALE_FI)

    def test_research_and_uygun_firewall(self) -> None:
        self.part_repo.rows = [_part_row("AIS", research_allowed=False)]
        with self.assertRaises(SnapshotReadError) as raised:
            read_turkiye_fund_canonical(
                participation_repo=self.part_repo,
                snapshot_repo=self.fi_repo,
                fund_code="AIS",
            )
        self.assertEqual(raised.exception.reason, REASON_RESEARCH_NOT_ALLOWED)
        self.part_repo.rows = [_part_row("AIS", status="Uygun Değil", research_allowed=True)]
        with self.assertRaises(SnapshotReadError) as raised:
            read_turkiye_fund_canonical(
                participation_repo=self.part_repo,
                snapshot_repo=self.fi_repo,
                fund_code="AIS",
            )
        self.assertEqual(raised.exception.reason, REASON_PARTICIPATION_NOT_UYGUN)

    def test_no_fresh_compute_and_readonly(self) -> None:
        source = READER.read_text(encoding="utf-8")
        self.assertNotIn("evaluate_official_fund_intelligence", source)
        self.assertNotIn("evaluate_turkiye_fund_participation", source)
        self.assertNotIn("default_tefas_fund_provider", source)
        self.assertNotIn("allocate_new_money", source)
        guarded_part = ReadOnlyRepository(self.part_repo)
        guarded_fi = ReadOnlyRepository(self.fi_repo)
        with patch(
            "services.official_tefas_product.default_tefas_fund_provider",
            side_effect=AssertionError("tefas_called"),
        ), patch(
            "services.fund_intelligence_engine.evaluate_official_fund_intelligence",
            side_effect=AssertionError("fi_called"),
        ), patch(
            "services.official_turkiye_fund_participation.evaluate_turkiye_fund_participation",
            side_effect=AssertionError("participation_called"),
        ), patch(
            "services.wealth_new_money_allocation.allocate_new_money",
            side_effect=AssertionError("new_money_called"),
        ):
            rows = read_pilot_canonical(
                participation_repo=guarded_part,
                snapshot_repo=guarded_fi,
                is_holding=True,
                portfolio_weight=5.0,
            )
        self.assertEqual(len(rows), 3)
        with self.assertRaises(SnapshotReadError) as raised:
            guarded_part.append_snapshot({})
        self.assertEqual(raised.exception.reason, REASON_WRITE_BLOCKED)
        with self.assertRaises(SnapshotReadError):
            guarded_fi.upsert({})

    def test_generic_8e_consumption(self) -> None:
        for code in ("AIS", "ZPE", "IAT"):
            loaded = read_turkiye_fund_canonical(
                participation_repo=self.part_repo,
                snapshot_repo=self.fi_repo,
                fund_code=code,
                is_holding=True,
                portfolio_weight=5.0,
            )
            self.assertEqual(loaded.decision.decision, DECISION_WATCH)
            self.assertFalse(loaded.decision.exposure_increase_allowed)
            bare = evaluate_snapshot_fund_decision(
                loaded.participation,
                loaded.fund_intelligence,
            )
            self.assertEqual(bare.decision, DECISION_WATCH)
            self.assertFalse(bare.exposure_increase_allowed)

    def test_production_read_only_uat(self) -> None:
        writes = 0
        rows = read_pilot_canonical(
            participation_repo=ReadOnlyRepository(self.part_repo),
            snapshot_repo=ReadOnlyRepository(self.fi_repo),
            is_holding=True,
            portfolio_weight=5.0,
        )
        self.assertEqual(writes, 0)
        self.assertEqual(len(self.part_repo.rows), 3)
        self.assertEqual(len(self.fi_repo.rows), 3)
        by_code = {row.fund_code: row for row in rows}
        self.assertEqual(by_code["AIS"].participation.row_id, ACCEPTED_PARTICIPATION_IDS["AIS"])
        self.assertEqual(by_code["ZPE"].participation.row_id, ACCEPTED_PARTICIPATION_IDS["ZPE"])
        self.assertEqual(by_code["IAT"].participation.row_id, ACCEPTED_PARTICIPATION_IDS["IAT"])
        self.assertEqual(by_code["AIS"].fund_intelligence.row_id, ACCEPTED_FI_IDS["AIS"])
        self.assertEqual(by_code["ZPE"].fund_intelligence.row_id, ACCEPTED_FI_IDS["ZPE"])
        self.assertEqual(by_code["IAT"].fund_intelligence.row_id, ACCEPTED_FI_IDS["IAT"])
        self.assertEqual(by_code["AIS"].fund_intelligence.score, 70.39)
        self.assertEqual(by_code["ZPE"].fund_intelligence.score, 66.32)
        self.assertEqual(by_code["IAT"].fund_intelligence.score, 60.49)
        iat_ybf = (
            (by_code["IAT"].fund_intelligence.raw_row.get("data_quality") or {})
            .get("source_as_of", {})
            .get("date_model", {})
            .get("kap_mandate", {})
            .get("value")
        )
        self.assertEqual(iat_ybf, "2026-02-27")

    def test_new_money_hybrid_and_regression(self) -> None:
        source = READER.read_text(encoding="utf-8")
        self.assertNotIn("allocate_new_money", source)
        self.assertNotIn("enable_hybrid_exposure_allocation", source)
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        self.assertTrue(callable(allocate_new_money))
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        from services.fund_intelligence_engine import evaluate_official_fund_intelligence

        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        sp = default_official_sp_funds_provider()
        tefas = default_tefas_fund_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertTrue(sp.supports(symbol))
            self.assertFalse(tefas.supports(symbol))
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertIn("persist_si", BIST_ORCH.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        self.assertNotIn("read_turkiye_fund_canonical", ORCHESTRATOR.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
