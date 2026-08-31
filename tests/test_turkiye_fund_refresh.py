from __future__ import annotations

import importlib.util
import os
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.bist_refresh_contract import REASON_LIVE_UNSAFE, REASON_NO_CHANGE
from services.fund_product_contract import (
    LAYER_CASH_LIKE,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
    PILOT_FUND_SYMBOLS,
    PILOT_TEFAS_FUND_CODES,
    REGION_TR,
)
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider
from services.official_turkiye_fund_participation import evaluate_pilot_participation
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    DECISION_WATCH,
    REASON_SI_NOT_ATTRACTIVE,
    REASON_SI_WATCH,
)
from services.turkiye_fund_refresh_contract import (
    CHANGE_PDR,
    CHANGE_TEFAS_PRICE,
    JOB_NAME,
    LAYER_ECONOMIC_EXPOSURE,
    LAYER_EIGHT_E,
    LAYER_FUND_INTELLIGENCE,
    LAYER_IDENTITY,
    LAYER_PARTICIPATION,
    STATUS_BLOCKED,
    STATUS_NO_CHANGE,
    STATUS_WOULD_PUBLISH,
    TABLE_PARTICIPATION_SNAPSHOTS,
    TABLE_SI_SNAPSHOTS,
)
from services.turkiye_fund_refresh_orchestrator import (
    compute_turkiye_fund_snapshots,
    run_turkiye_fund_refresh,
)
from services.turkiye_fund_snapshot import (
    assert_ais_not_portfolio_cash,
    economic_exposure_snapshot,
    eight_e_snapshot,
    identity_snapshot,
    source_as_of_bundle,
)
from services.wealth_new_money_allocation import allocate_new_money
from tests.test_turkiye_fund_8e import FROZEN_FI

SNAPSHOT = Path("services/turkiye_fund_snapshot.py")
ORCHESTRATOR = Path("services/turkiye_fund_refresh_orchestrator.py")
CONTRACT = Path("services/turkiye_fund_refresh_contract.py")
PERSISTENCE = Path("services/turkiye_fund_persistence.py")
CLI = Path("scripts/run_turkiye_fund_refresh.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
HYBRID = Path("services/hybrid_exposure_allocation_policy.py")
BIST = Path("services/bist_refresh_contract.py")
US_SI = Path("services/security_intelligence_engine.py")
TEFAS = Path("services/official_tefas_product.py")

CALCULATED_AT = "2026-08-30T21:00:00+00:00"
FROZEN_EXPOSURE = {
    "AIS": (LAYER_CASH_LIKE, REGION_TR, "MEDIUM"),
    "ZPE": ("equity", REGION_TR, "MEDIUM"),
    "IAT": ("sukuk", REGION_TR, "MEDIUM"),
}
FROZEN_8E_REASON = {
    "AIS": REASON_SI_WATCH,
    "ZPE": REASON_SI_WATCH,
    "IAT": REASON_SI_NOT_ATTRACTIVE,
}


class _ProviderProxy:
    def __init__(
        self,
        inner,
        *,
        fail_tefas: bool = False,
        fail_pdr: bool = False,
        tefas_last: str | None = None,
        pdr_period: str | None = None,
    ) -> None:
        self._inner = inner
        self._fail_tefas = fail_tefas
        self._fail_pdr = fail_pdr
        self._tefas_last = tefas_last
        self._pdr_period = pdr_period

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def price_history(self, symbol: str, *, period_months: int = 12):
        if self._fail_tefas:
            raise RuntimeError("tefas_unavailable")
        series = self._inner.price_history(symbol, period_months=period_months)
        if self._tefas_last:
            return replace(series, last_date=self._tefas_last)
        return series

    def pdr_holdings(self, symbol: str):
        if self._fail_pdr:
            raise RuntimeError("pdr_unavailable")
        file = self._inner.pdr_holdings(symbol)
        if self._pdr_period and file is not None:
            return replace(file, report_period=self._pdr_period)
        return file


def _layer(run, fund_code: str, layer: str):
    for fund in run.funds:
        if fund.fund_code == fund_code:
            for row in fund.layers:
                if row.layer == layer:
                    return row
    raise AssertionError(f"missing {fund_code}/{layer}")


class TurkiyeFundRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = default_tefas_fund_provider()
        self.stamp = CALCULATED_AT

    def test_canonical_payloads_preserve_frozen_state(self) -> None:
        for code, (score, state) in FROZEN_FI.items():
            bundle = compute_turkiye_fund_snapshots(code, calculated_at=self.stamp)
            identity = bundle[LAYER_IDENTITY]
            participation = bundle[LAYER_PARTICIPATION]
            fi = bundle[LAYER_FUND_INTELLIGENCE]
            exposure = bundle[LAYER_ECONOMIC_EXPOSURE]
            eight = bundle[LAYER_EIGHT_E]
            self.assertEqual(identity.instrument, "FUND")
            self.assertEqual(identity.market, "TR")
            self.assertTrue(identity.publishable)
            self.assertIsNone(identity.target_table)
            self.assertEqual(participation.payload["status"], PARTICIPATION_STATUS_UYGUN)
            self.assertTrue(participation.payload["research_allowed"])
            self.assertEqual(participation.payload["methodology_id"], METHODOLOGY_TURKIYE_FUND_PARTICIPATION)
            self.assertEqual(participation.target_table, TABLE_PARTICIPATION_SNAPSHOTS)
            self.assertTrue(participation.publishable)
            self.assertEqual(fi.payload["overall_score"], score)
            self.assertEqual(fi.payload["investment_state"], state)
            self.assertEqual(fi.target_table, TABLE_SI_SNAPSHOTS)
            self.assertTrue(fi.publishable)
            self.assertIsNotNone(fi.payload["data_quality"]["completeness"])
            self.assertIsNotNone(fi.payload["overall_confidence"])
            layer, geo, conf = FROZEN_EXPOSURE[code]
            self.assertEqual(exposure.payload["primary_exposure"], layer)
            self.assertEqual(exposure.payload["geography"], geo)
            self.assertEqual(exposure.payload["confidence"], conf)
            self.assertEqual(exposure.target_table, TABLE_SI_SNAPSHOTS)
            self.assertTrue(exposure.publishable)
            self.assertEqual(eight.payload["decision"], DECISION_WATCH)
            self.assertNotEqual(eight.payload["decision"], DECISION_INSUFFICIENT_DATA)
            self.assertFalse(eight.payload["increase_allowed"])
            self.assertFalse(eight.payload["exposure_increase_allowed"])
            self.assertIn(FROZEN_8E_REASON[code], eight.payload["blocking_reasons"])
            self.assertTrue(eight.publishable)
            self.assertIsNone(eight.target_table)

    def test_source_as_of_is_not_calculated_at(self) -> None:
        bundle = compute_turkiye_fund_snapshots("AIS", calculated_at=self.stamp)
        sources = bundle["source_as_of"]
        self.assertEqual(sources["tefas_price"], "2026-08-28")
        self.assertEqual(sources["kap_pdr"], "2026-07")
        self.assertEqual(sources["kap_izahname"], "2026-01-13")
        self.assertEqual(sources["kap_mandate"], "2026-01-13")
        iat = compute_turkiye_fund_snapshots("IAT", calculated_at=self.stamp)
        self.assertEqual(iat["source_as_of"]["kap_mandate"], "2026-02-27")
        self.assertNotEqual(iat["source_as_of"]["kap_mandate"], "2027-02-27")
        for layer in (
            LAYER_IDENTITY,
            LAYER_PARTICIPATION,
            LAYER_FUND_INTELLIGENCE,
            LAYER_ECONOMIC_EXPOSURE,
            LAYER_EIGHT_E,
        ):
            snapshot = bundle[layer]
            self.assertEqual(snapshot.calculated_at, self.stamp)
            self.assertNotEqual(snapshot.calculated_at, snapshot.source_as_of["tefas_price"])
            self.assertNotEqual(snapshot.calculated_at, snapshot.source_as_of["kap_pdr"])
            self.assertEqual(snapshot.source_as_of["tefas_price"], "2026-08-28")
            self.assertEqual(snapshot.source_as_of["kap_pdr"], "2026-07")
        self.assertEqual(bundle[LAYER_FUND_INTELLIGENCE].payload["as_of"], "2026-08-28")
        self.assertEqual(bundle[LAYER_ECONOMIC_EXPOSURE].payload["as_of"], "2026-07")

    def test_ais_cash_like_never_serializes_as_portfolio_cash(self) -> None:
        bundle = compute_turkiye_fund_snapshots("AIS", calculated_at=self.stamp)
        exposure = bundle[LAYER_ECONOMIC_EXPOSURE]
        fi = bundle[LAYER_FUND_INTELLIGENCE]
        self.assertEqual(exposure.payload["primary_exposure"], LAYER_CASH_LIKE)
        self.assertNotEqual(exposure.payload["primary_exposure"], "cash")
        self.assertNotEqual(exposure.payload["primary_exposure"], "CASH")
        nested = fi.payload["data_quality"]["economic_exposure"]["primary_exposure"]
        self.assertEqual(nested, LAYER_CASH_LIKE)
        self.assertNotEqual(nested, "cash")
        encoded = str(exposure.to_dict()) + str(fi.to_dict())
        self.assertNotIn("'primary_exposure': 'cash'", encoded)
        self.assertNotIn('"primary_exposure": "cash"', encoded)
        assert_ais_not_portfolio_cash(exposure)
        assert_ais_not_portfolio_cash(fi)
        cash = replace(self.provider.economic_classification("AIS"), primary_exposure="cash")
        with self.assertRaises(ValueError):
            economic_exposure_snapshot(
                cash,
                fund_code="AIS",
                source_as_of=bundle["source_as_of"],
                calculated_at=self.stamp,
            )

    def test_idempotency_key_ignores_calculated_at(self) -> None:
        first = compute_turkiye_fund_snapshots("ZPE", calculated_at="2026-08-30T10:00:00+00:00")
        second = compute_turkiye_fund_snapshots("ZPE", calculated_at="2026-08-30T11:00:00+00:00")
        for layer in (
            LAYER_IDENTITY,
            LAYER_PARTICIPATION,
            LAYER_FUND_INTELLIGENCE,
            LAYER_ECONOMIC_EXPOSURE,
            LAYER_EIGHT_E,
        ):
            self.assertEqual(first[layer].idempotency_key, second[layer].idempotency_key)
            self.assertNotEqual(first[layer].calculated_at, second[layer].calculated_at)
            self.assertNotIn(first[layer].calculated_at, first[layer].idempotency_key)

    def test_same_evidence_is_no_change(self) -> None:
        first = run_turkiye_fund_refresh(calculated_at=self.stamp)
        second = run_turkiye_fund_refresh(
            calculated_at="2026-08-30T22:00:00+00:00",
            previous_state=first.next_state,
        )
        self.assertEqual(first.status, "DRY_RUN")
        self.assertEqual(first.would_publish, 15)
        self.assertEqual(first.no_change, 0)
        self.assertEqual(first.writes, 0)
        self.assertEqual(second.status, "DRY_RUN")
        self.assertEqual(second.would_publish, 0)
        self.assertEqual(second.no_change, 15)
        self.assertEqual(second.blocked, 0)
        self.assertEqual(second.writes, 0)
        self.assertEqual(second.changes_detected, 0)
        for fund in second.funds:
            for layer in fund.layers:
                self.assertEqual(layer.status, STATUS_NO_CHANGE)
                self.assertEqual(layer.reason, REASON_NO_CHANGE)

    def test_changed_tefas_date_is_meaningful_change(self) -> None:
        baseline = run_turkiye_fund_refresh(calculated_at=self.stamp)
        changed = run_turkiye_fund_refresh(
            calculated_at=self.stamp,
            previous_state=baseline.next_state,
            provider=_ProviderProxy(self.provider, tefas_last="2026-08-29"),
        )
        self.assertGreater(changed.would_publish, 0)
        self.assertGreater(changed.changes_detected, 0)
        ais_fi = _layer(changed, "AIS", LAYER_FUND_INTELLIGENCE)
        self.assertEqual(ais_fi.status, STATUS_WOULD_PUBLISH)
        self.assertIn(CHANGE_TEFAS_PRICE, ais_fi.changes)

    def test_changed_pdr_is_meaningful_change(self) -> None:
        baseline = run_turkiye_fund_refresh(calculated_at=self.stamp)
        changed = run_turkiye_fund_refresh(
            calculated_at=self.stamp,
            previous_state=baseline.next_state,
            provider=_ProviderProxy(self.provider, pdr_period="2026-06"),
        )
        self.assertGreater(changed.would_publish, 0)
        zpe_exposure = _layer(changed, "ZPE", LAYER_ECONOMIC_EXPOSURE)
        self.assertEqual(zpe_exposure.status, STATUS_WOULD_PUBLISH)
        self.assertIn(CHANGE_PDR, zpe_exposure.changes)

    def test_dry_run_always_writes_zero(self) -> None:
        run = run_turkiye_fund_refresh()
        self.assertTrue(run.dry_run)
        self.assertEqual(run.writes, 0)
        self.assertEqual(run.job_name, JOB_NAME)
        self.assertTrue(run.run_id)
        self.assertTrue(run.started_at)
        self.assertTrue(run.finished_at)
        self.assertEqual(run.symbols, PILOT_TEFAS_FUND_CODES)
        self.assertFalse(run.persist_fund_intelligence)
        self.assertFalse(run.persist_participation)
        self.assertFalse(run.persist_economic_exposure)
        self.assertFalse(run.persist_decisions)
        self.assertFalse(run.allow_live)
        for fund in run.funds:
            self.assertFalse(any(layer.published for layer in fund.layers))

    def test_credentials_cannot_enable_writes(self) -> None:
        env = {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/nabi",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            dry = run_turkiye_fund_refresh()
            forbidden = run_turkiye_fund_refresh(
                dry_run=False,
                persist_fund_intelligence=True,
                persist_participation=True,
                persist_economic_exposure=True,
                persist_decisions=True,
                allow_live=True,
                cli_live=True,
            )
            live_no_repos = run_turkiye_fund_refresh(
                persist_fund_intelligence=True,
                persist_participation=True,
                cli_live=True,
            )
        self.assertEqual(dry.writes, 0)
        self.assertTrue(dry.dry_run)
        self.assertEqual(forbidden.writes, 0)
        self.assertTrue(forbidden.dry_run)
        self.assertEqual(forbidden.status, "LIVE_BLOCKED")
        self.assertEqual(live_no_repos.writes, 0)
        self.assertTrue(live_no_repos.dry_run)
        self.assertEqual(live_no_repos.status, "LIVE_BLOCKED")
        for fund in live_no_repos.funds:
            self.assertFalse(any(layer.published for layer in fund.layers))
            part = _layer(live_no_repos, fund.fund_code, LAYER_PARTICIPATION)
            fi = _layer(live_no_repos, fund.fund_code, LAYER_FUND_INTELLIGENCE)
            self.assertEqual(part.status, STATUS_BLOCKED)
            self.assertEqual(part.reason, REASON_LIVE_UNSAFE)
            self.assertEqual(fi.status, STATUS_BLOCKED)
            self.assertEqual(fi.reason, REASON_LIVE_UNSAFE)
        source = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertNotIn("DATABASE_URL", source)
        self.assertNotIn("supabase", source.lower())
        self.assertNotIn("create_admin_supabase_client", source)

    def test_upstream_failure_blocks_dependent_layers(self) -> None:
        tefas_fail = run_turkiye_fund_refresh(
            symbols=("AIS",),
            provider=_ProviderProxy(self.provider, fail_tefas=True),
        )
        fi = _layer(tefas_fail, "AIS", LAYER_FUND_INTELLIGENCE)
        eight = _layer(tefas_fail, "AIS", LAYER_EIGHT_E)
        self.assertEqual(fi.status, STATUS_BLOCKED)
        self.assertFalse(fi.publishable)
        self.assertEqual(eight.status, STATUS_BLOCKED)
        self.assertFalse(eight.publishable)
        self.assertEqual(tefas_fail.writes, 0)
        pdr_fail = run_turkiye_fund_refresh(
            symbols=("ZPE",),
            provider=_ProviderProxy(self.provider, fail_pdr=True),
        )
        exposure = _layer(pdr_fail, "ZPE", LAYER_ECONOMIC_EXPOSURE)
        eight_zpe = _layer(pdr_fail, "ZPE", LAYER_EIGHT_E)
        self.assertEqual(exposure.status, STATUS_BLOCKED)
        self.assertFalse(exposure.publishable)
        self.assertEqual(eight_zpe.status, STATUS_BLOCKED)
        self.assertFalse(eight_zpe.publishable)
        participation = _layer(pdr_fail, "ZPE", LAYER_PARTICIPATION)
        self.assertIn(participation.status, {STATUS_WOULD_PUBLISH, STATUS_NO_CHANGE})

    def test_new_money_and_hybrid_remain_off(self) -> None:
        for path in (SNAPSHOT, ORCHESTRATOR, CONTRACT, PERSISTENCE, CLI):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("allocate_new_money", source)
            self.assertNotIn("enable_hybrid_exposure_allocation", source)
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        self.assertTrue(callable(allocate_new_money))
        with patch(
            "services.wealth_new_money_allocation.allocate_new_money",
            side_effect=AssertionError("new_money_called"),
        ):
            run = run_turkiye_fund_refresh(symbols=("IAT",))
        self.assertEqual(run.writes, 0)
        self.assertEqual(run.status, "DRY_RUN")

    def test_sp_funds_bist_us_regression(self) -> None:
        from services.fund_intelligence_engine import evaluate_official_fund_intelligence

        self.assertEqual(evaluate_official_fund_intelligence("SPUS").score, 71.41)
        self.assertEqual(evaluate_official_fund_intelligence("SPSK").score, 65.87)
        self.assertEqual(evaluate_official_fund_intelligence("SPRE").score, 47.57)
        self.assertEqual(evaluate_official_fund_intelligence("SPWO").score, 52.79)
        sp = default_official_sp_funds_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertTrue(sp.supports(symbol))
            self.assertFalse(self.provider.supports(symbol))
        self.assertTrue(BIST.is_file())
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertNotIn("AIS", US_SI.read_text(encoding="utf-8"))
        self.assertNotIn("allocate_new_money", TEFAS.read_text(encoding="utf-8"))

    def test_cli_default_is_dry_run_and_refuses_live(self) -> None:
        spec = importlib.util.spec_from_file_location("run_turkiye_fund_refresh_cli", CLI)
        assert spec is not None and spec.loader is not None
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        args = SimpleNamespace(
            dry_run=True,
            live=True,
            allow_live=False,
            allow_broad=False,
            persist_fund_intelligence=False,
            persist_participation=False,
            persist_economic_exposure=False,
            persist_decisions=False,
        )
        self.assertTrue(cli.live_requested(args))
        self.assertFalse(cli.writes_enabled(args))
        self.assertEqual(cli.main(["--live"]), 0)
        self.assertEqual(cli.main(["--persist-participation"]), 0)
        self.assertEqual(cli.main(["--persist-fund-intelligence"]), 0)
        self.assertEqual(cli.main(["--persist-decisions"]), 1)
        self.assertEqual(cli.main(["--persist-economic-exposure"]), 1)
        cli_source = CLI.read_text(encoding="utf-8")
        self.assertIn("attach_production_repos", cli_source)
        self.assertNotIn("DATABASE_URL", cli_source)
        self.assertIn("create_admin_supabase_client", cli_source)

    def test_watch_is_not_rewritten_as_insufficient(self) -> None:
        from services.fund_decision_readiness import evaluate_official_fund_decision

        decision = evaluate_official_fund_decision("IAT")
        snapshot = eight_e_snapshot(
            decision,
            source_as_of=source_as_of_bundle(
                tefas_price="2026-08-28",
                kap_pdr="2026-07",
                kap_mandate="2022-07-08",
                kap_izahname="2022-07-08",
            ),
            calculated_at=self.stamp,
            upstream_ready=True,
        )
        self.assertEqual(snapshot.payload["decision"], DECISION_WATCH)
        self.assertNotEqual(snapshot.payload["decision"], DECISION_INSUFFICIENT_DATA)
        self.assertFalse(snapshot.payload["increase_allowed"])
        self.assertTrue(snapshot.publishable)

    def test_participation_uses_existing_table_contract(self) -> None:
        verdict = evaluate_pilot_participation("AIS")
        bundle = compute_turkiye_fund_snapshots("AIS", calculated_at=self.stamp)
        row = bundle[LAYER_PARTICIPATION]
        self.assertEqual(verdict.participation_status, PARTICIPATION_STATUS_UYGUN)
        self.assertEqual(row.payload["symbol"], "AIS")
        self.assertEqual(row.payload["assessment_payload"]["instrument"], "FUND")
        self.assertEqual(row.payload["assessment_payload"]["market"], "TR")
        self.assertIn("semantic_identity", row.payload)
        self.assertIn("source_evidence", row.payload)
        identity = identity_snapshot(
            self.provider.turkiye_identity("AIS"),
            source_as_of=bundle["source_as_of"],
            calculated_at=self.stamp,
        )
        self.assertEqual(identity.payload["identity_status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
