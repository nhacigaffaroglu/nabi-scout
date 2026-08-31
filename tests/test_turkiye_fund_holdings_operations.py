from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.candidate_price_service import CandidatePriceService
from services.fund_product_contract import LAYER_CASH_LIKE, PILOT_FUND_SYMBOLS, PILOT_TEFAS_FUND_CODES
from services.hybrid_exposure_allocation_policy import HybridExposureAllocationPolicy
from services.nabi_adviser_context import build_nabi_adviser_context
from services.official_sp_funds_product import default_official_sp_funds_provider
from services.official_tefas_product import default_tefas_fund_provider
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_management_service import PortfolioManagementService
from services.portfolio_security_decision_contract import DECISION_WATCH
from services.turkiye_fund_persistence import MemorySecurityIntelligenceSnapshotRepository
from services.turkiye_fund_portfolio_integration import (
    ais_satisfies_portfolio_cash,
    exposure_maps_to_portfolio_cash,
    format_turkiye_fund_adviser_narrative,
    load_turkiye_fund_portfolio_contexts,
    run_turkiye_new_money_uat,
    turkiye_fund_adviser_facts,
)
from services.turkiye_fund_price_reader import (
    FROZEN_CAPTURED_UNIT_PRICES,
    PRICE_SOURCE,
    REASON_MISSING_PRICE,
    market_value_try,
    quote_turkiye_fund_unit_price,
    read_turkiye_fund_unit_price,
)
from services.turkiye_fund_refresh_contract import JOB_NAME
from services.turkiye_fund_refresh_orchestrator import (
    compute_turkiye_fund_snapshots,
    run_turkiye_fund_refresh,
)
from services.turkiye_fund_snapshot_reader import (
    REASON_FI_MISSING,
    REASON_INCOMPATIBLE_FI_VERSION,
    REASON_PARTICIPATION_MISSING,
    REASON_PARTICIPATION_NOT_UYGUN,
    REASON_RESEARCH_NOT_ALLOWED,
    REASON_STALE_FI,
    load_turkiye_fund_canonical_from_client,
)
from services.wealth_asset_classification import resolve_asset_metadata
from services.wealth_contract import ASSET_CLASS_CASH, ASSET_CLASS_ETF, ASSET_CLASS_FUND, WealthValidationError
from services.wealth_new_money_allocation import REASON_EXPOSURE_INCREASE_NOT_ALLOWED
from services.wealth_price_service import is_cash_asset
from tests.test_turkiye_fund_8e import FROZEN_FI
from tests.test_turkiye_fund_snapshot_read import _fi_row, _seeded_repos
from tests.test_wealth_new_money_allocation import _exposure_policy, _fx, _row, _view

HOLDINGS = Path("services/turkiye_fund_price_reader.py")
INTEGRATION = Path("services/turkiye_fund_portfolio_integration.py")
ADVISER = Path("services/nabi_adviser_context.py")
FUND_REPORT = Path("pages/9_Fund_Report.py")
CLI = Path("scripts/run_turkiye_fund_refresh.py")
WORKFLOW = Path(".github/workflows/daily_turkiye_fund_refresh.yml")
BIST_WORKFLOW = Path(".github/workflows/daily_bist_refresh.yml")
US_HOLDINGS_WORKFLOW = Path(".github/workflows/daily_fund_holdings_refresh.yml")
GOAL = Path("services/wealth_goal_planning.py")
NEW_MONEY = Path("services/wealth_new_money_allocation.py")
BIST = Path("services/bist_refresh_contract.py")
US_SI = Path("services/security_intelligence_engine.py")
FX = Path("services/fx_conversion_engine.py")
WEALTH_CORE = Path("services/wealth_core_service.py")

UAT_QTY = {"AIS": 5_000.0, "ZPE": 20.0, "IAT": 8_000.0}


def _priced_view():
    rows = []
    total = 0.0
    for code, qty in UAT_QTY.items():
        price = FROZEN_CAPTURED_UNIT_PRICES[code]
        mv = qty * price
        total += mv
        rows.append(
            _row(
                code,
                market_value=mv,
                weight_pct=0.0,
                asset_class=ASSET_CLASS_FUND,
                price=price,
                currency="TRY",
            )
        )
    for row in rows:
        object.__setattr__(row, "weight_pct", (row.market_value / total) * 100.0)
        object.__setattr__(row, "included_in_base_totals", True)
    cash = _row("CASH", market_value=100_000, weight_pct=0, asset_class="cash", price=1.0, currency="TRY")
    object.__setattr__(cash, "is_cash", True)
    object.__setattr__(cash, "included_in_base_totals", True)
    total_with_cash = total + 100_000
    for row in [*rows, cash]:
        object.__setattr__(row, "weight_pct", (float(row.market_value or 0) / total_with_cash) * 100.0)
    view = _view([*rows, cash])
    object.__setattr__(view, "base_currency", "TRY")
    return view, total, total_with_cash


class TurkiyeFundHoldingsOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.part_repo, self.fi_repo = _seeded_repos()
        self.view, self.fund_mv, self.total_mv = _priced_view()

    def test_wealth_holdings_are_fund_tr_try(self) -> None:
        for code in PILOT_TEFAS_FUND_CODES:
            asset_class, market, kind, status = resolve_asset_metadata(code, currency="USD")
            self.assertEqual(asset_class, ASSET_CLASS_FUND)
            self.assertEqual(market, "TR")
            self.assertEqual(kind, "fund")
            self.assertEqual(status, "RESOLVED")
            wealth = MagicMock()
            wealth.register_asset.return_value = {"id": f"asset-{code}"}
            wealth.post_transaction.return_value = {"id": f"txn-{code}"}
            PortfolioManagementService(wealth).add_holding(
                account_id="acc-1",
                symbol=code,
                quantity=UAT_QTY[code],
                average_cost=FROZEN_CAPTURED_UNIT_PRICES[code],
                currency="TRY",
                asset_class=ASSET_CLASS_FUND,
                market="US",
            )
            kwargs = wealth.register_asset.call_args.kwargs
            self.assertEqual(kwargs["symbol"], code)
            self.assertEqual(kwargs["market"], "TR")
            self.assertEqual(kwargs["asset_class"], ASSET_CLASS_FUND)
            self.assertEqual(kwargs["currency"], "TRY")
            txn = wealth.post_transaction.call_args.kwargs
            self.assertEqual(txn["txn_type"], "buy")
            self.assertEqual(txn["quantity"], UAT_QTY[code])
            self.assertEqual(txn["currency"], "TRY")
            self.assertEqual(txn["price"], FROZEN_CAPTURED_UNIT_PRICES[code])

    def test_ais_cash_buy_is_rejected(self) -> None:
        wealth = MagicMock()
        with self.assertRaises(WealthValidationError):
            PortfolioManagementService(wealth).add_holding(
                account_id="acc-1",
                symbol="AIS",
                quantity=1000,
                average_cost=1.0,
                currency="TRY",
                asset_class=ASSET_CLASS_CASH,
            )
        wealth.ensure_cash_asset.assert_not_called()
        wealth.post_transaction.assert_not_called()

    def test_valuation_from_canonical_snapshot_price(self) -> None:
        table = []
        for code in PILOT_TEFAS_FUND_CODES:
            quote = read_turkiye_fund_unit_price(self.fi_repo, code)
            self.assertTrue(quote.available)
            self.assertEqual(quote.currency, "TRY")
            self.assertEqual(quote.source, PRICE_SOURCE)
            self.assertAlmostEqual(quote.price, FROZEN_CAPTURED_UNIT_PRICES[code])
            mv = market_value_try(UAT_QTY[code], quote.price)
            weight = mv / self.total_mv * 100.0
            table.append((code, UAT_QTY[code], quote.price, mv, weight))
        self.assertEqual([row[0] for row in table], ["AIS", "ZPE", "IAT"])
        service = CandidatePriceService(MagicMock())
        with patch(
            "services.candidate_price_service.quote_turkiye_fund_unit_price",
            side_effect=lambda symbol, **_k: read_turkiye_fund_unit_price(
                self.fi_repo, symbol
            ).to_quote(),
        ):
            for code, qty, price, mv, _weight in table:
                quoted = service.get_quote_for_asset(code, ASSET_CLASS_FUND, "TRY", market="TR")
                self.assertTrue(quoted.available)
                self.assertEqual(quoted.source, PRICE_SOURCE)
                self.assertNotEqual(quoted.source, "nominal_cash")
                self.assertAlmostEqual(quoted.price, price)
                self.assertAlmostEqual(market_value_try(qty, quoted.price), mv)
        missing = MemorySecurityIntelligenceSnapshotRepository()
        missing.rows.append(_fi_row("AIS", data_quality={"completeness": 1.0, "economic_exposure": {
            "primary_exposure": LAYER_CASH_LIKE,
            "geography": "TR",
            "confidence": "MEDIUM",
        }}))
        blank = read_turkiye_fund_unit_price(missing, "AIS")
        self.assertFalse(blank.available)
        self.assertEqual(blank.error, REASON_MISSING_PRICE)
        self.assertIsNone(blank.price)

    def test_live_portfolio_context_uses_actual_holdings(self) -> None:
        empty = {row.fund_code: row for row in load_turkiye_fund_portfolio_contexts(
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
        )}
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertFalse(empty[code].is_holding)
            self.assertIsNone(empty[code].quantity)
            self.assertIsNone(empty[code].market_value)
        held = {row.fund_code: row for row in load_turkiye_fund_portfolio_contexts(
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
            portfolio_view=self.view,
        )}
        for code, qty in UAT_QTY.items():
            row = held[code]
            self.assertTrue(row.is_holding)
            self.assertAlmostEqual(row.quantity, qty)
            self.assertAlmostEqual(row.market_value, qty * FROZEN_CAPTURED_UNIT_PRICES[code])
            self.assertGreater(row.portfolio_weight, 0)
            self.assertEqual(row.instrument, "FUND")
            self.assertEqual(row.market, "TR")
            self.assertEqual(row.participation_status, PARTICIPATION_STATUS_UYGUN)
            score, state = FROZEN_FI[code]
            self.assertEqual(row.fi_score, score)
            self.assertEqual(row.fi_state, state)
            self.assertEqual(row.eight_e, DECISION_WATCH)
            self.assertFalse(row.increase_allowed)
        self.assertEqual(held["AIS"].primary_exposure, LAYER_CASH_LIKE)
        self.assertEqual(held["ZPE"].primary_exposure, "equity")
        self.assertEqual(held["IAT"].primary_exposure, "sukuk")

    def test_adviser_reads_canonical_context(self) -> None:
        contexts = load_turkiye_fund_portfolio_contexts(
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
            portfolio_view=self.view,
        )
        iat = next(row for row in contexts if row.fund_code == "IAT")
        narrative = format_turkiye_fund_adviser_narrative(iat)
        self.assertIn("IAT katılım açısından uygun.", narrative)
        self.assertIn("Fund Intelligence 60.49 NEUTRAL.", narrative)
        self.assertIn("Portföy kararı WATCH", narrative)
        self.assertIn("increase_allowed=false", narrative)
        self.assertIn("yeni para tahsisi yapılmıyor", narrative)
        facts = turkiye_fund_adviser_facts(iat)
        self.assertEqual(facts["fund_identity"]["instrument"], "FUND")
        self.assertEqual(facts["holding_state"], "held")
        self.assertFalse(facts["increase_allowed"])
        self.assertEqual(facts["new_money_block_reason"], REASON_EXPOSURE_INCREASE_NOT_ALLOWED)
        adviser = build_nabi_adviser_context(
            "IAT katılım açısından uygun mu?",
            turkiye_fund_contexts=contexts,
        )
        self.assertEqual(adviser.canonical_answer, narrative)
        self.assertEqual(adviser.wealth_context["turkiye_fund"]["fi_state"], "NEUTRAL")
        self.assertNotIn("openai", narrative.lower())

    def test_new_money_still_zero_when_held(self) -> None:
        from tests.test_nabi_adviser_8f import _psd
        from services.portfolio_security_decision_contract import DECISION_HOLD

        contexts = load_turkiye_fund_portfolio_contexts(
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
            portfolio_view=self.view,
        )
        uat = run_turkiye_new_money_uat(
            portfolio_view=self.view,
            policy=_exposure_policy(equity=50, sukuk=40, cash=10),
            contexts=contexts,
            conversion=_fx(),
            extra_decisions=(_psd("CASH", DECISION_HOLD, increase=True),),
            price_by_symbol=FROZEN_CAPTURED_UNIT_PRICES,
        )
        self.assertEqual(uat.turkish_allocated, Decimal("0"))
        for code in PILOT_TEFAS_FUND_CODES:
            self.assertEqual(uat.by_fund[code], Decimal("0"))
            self.assertIn(REASON_EXPOSURE_INCREASE_NOT_ALLOWED, uat.skip_reasons[code])
        self.assertFalse(HybridExposureAllocationPolicy().enabled)

    def test_ais_cash_firewall(self) -> None:
        contexts = load_turkiye_fund_portfolio_contexts(
            participation_repo=self.part_repo,
            snapshot_repo=self.fi_repo,
            portfolio_view=self.view,
        )
        ais = next(row for row in contexts if row.fund_code == "AIS")
        self.assertTrue(ais.is_holding)
        self.assertGreater(ais.market_value, 0)
        self.assertEqual(ais.primary_exposure, LAYER_CASH_LIKE)
        self.assertFalse(ais_satisfies_portfolio_cash(ais))
        self.assertFalse(exposure_maps_to_portfolio_cash(ais.primary_exposure))
        self.assertFalse(is_cash_asset("AIS", ASSET_CLASS_FUND))
        self.assertNotEqual(resolve_asset_metadata("AIS", currency="TRY")[0], ASSET_CLASS_CASH)
        cash_rows = [row for row in self.view.priced_positions if row.is_cash]
        self.assertTrue(cash_rows)
        self.assertNotIn("AIS", {row.symbol for row in cash_rows})
        residual = self.view.priced_total_market_value
        self.assertGreater(residual, ais.market_value)

    def test_refresh_pipeline_and_observability(self) -> None:
        bundle = compute_turkiye_fund_snapshots("AIS", calculated_at="2026-08-30T21:00:00+00:00")
        quality = bundle["fund_intelligence"].payload["data_quality"]
        self.assertAlmostEqual(quality["unit_price"], FROZEN_CAPTURED_UNIT_PRICES["AIS"])
        self.assertEqual(quality["unit_price_currency"], "TRY")
        self.assertEqual(quality["unit_price_source"], "TEFAS")
        first = run_turkiye_fund_refresh(calculated_at="2026-08-30T21:00:00+00:00")
        payload = first.to_dict()
        for key in (
            "run_id",
            "job_name",
            "started_at",
            "finished_at",
            "status",
            "funds",
            "source_changes_detected",
            "errors",
            "write_count",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["job_name"], JOB_NAME)
        self.assertEqual(payload["status"], "DRY_RUN")
        self.assertEqual(payload["write_count"], 0)
        self.assertEqual(payload["symbols"], list(PILOT_TEFAS_FUND_CODES))
        self.assertIn("processed", payload["participation"])
        self.assertIn("published", payload["participation"])
        self.assertIn("skipped", payload["participation"])
        self.assertIn("processed", payload["fund_intelligence"])
        self.assertIn("published", payload["fund_intelligence"])
        self.assertIn("skipped", payload["fund_intelligence"])
        second = run_turkiye_fund_refresh(
            calculated_at="2026-08-30T22:00:00+00:00",
            previous_state=first.next_state,
        )
        self.assertEqual(second.writes, 0)
        self.assertEqual(second.changes_detected, 0)
        self.assertTrue(second.dry_run)

    def test_scheduler_is_safe_and_isolated(self) -> None:
        from scripts.run_turkiye_fund_refresh import parse_args, resolve_execution_mode

        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('cron: "0 16 * * 1-5"', workflow)
        self.assertIn("19:00 Europe/Istanbul", workflow)
        self.assertIn("UTC+3", workflow)
        self.assertIn("--live", workflow)
        self.assertIn("--persist-fund-intelligence", workflow)
        self.assertIn("--persist-participation", workflow)
        self.assertNotIn("run_bist_refresh.py", workflow)
        self.assertNotIn("post_transaction", workflow)
        self.assertNotIn("register_asset", workflow)
        self.assertNotIn("allocate_new_money", workflow)
        bist = BIST_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('cron: "30 15 * * 1-5"', bist)
        self.assertNotEqual('cron: "0 16 * * 1-5"', 'cron: "30 15 * * 1-5"')
        us = US_HOLDINGS_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("run_daily_fund_holdings_refresh.py", us)
        self.assertNotIn("run_turkiye_fund_refresh.py", us)
        mode = resolve_execution_mode(parse_args([]))
        self.assertTrue(mode["dry_run"])
        self.assertFalse(mode["persist_participation"])
        self.assertFalse(mode["persist_fund_intelligence"])
        live = resolve_execution_mode(
            parse_args(["--live", "--persist-fund-intelligence", "--persist-participation"])
        )
        self.assertFalse(live["dry_run"])
        self.assertTrue(live["persist_participation"])
        self.assertIn("AIS,ZPE,IAT", CLI.read_text(encoding="utf-8") + ",".join(PILOT_TEFAS_FUND_CODES))

    def test_fail_closed_never_live_computes(self) -> None:
        reasons = (
            REASON_PARTICIPATION_MISSING,
            REASON_PARTICIPATION_NOT_UYGUN,
            REASON_RESEARCH_NOT_ALLOWED,
            REASON_FI_MISSING,
            REASON_STALE_FI,
            REASON_INCOMPATIBLE_FI_VERSION,
            REASON_MISSING_PRICE,
        )
        for reason in reasons:
            ctx = load_turkiye_fund_portfolio_contexts(
                participation_repo=self.part_repo,
                snapshot_repo=MemorySecurityIntelligenceSnapshotRepository(),
                fund_codes=("ZPE",),
            )[0]
            if reason == REASON_FI_MISSING:
                self.assertEqual(ctx.unavailable_reason, REASON_FI_MISSING)
                self.assertFalse(ctx.increase_allowed)
        with self.assertRaises(Exception):
            load_turkiye_fund_canonical_from_client(None, "AIS")

    def test_no_fresh_tefas_kap_from_consumers(self) -> None:
        consumer_files = (HOLDINGS, INTEGRATION, ADVISER, FUND_REPORT)
        for path in consumer_files:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("default_tefas_fund_provider", source)
            self.assertNotIn("evaluate_official_fund_intelligence", source)
            self.assertNotIn("evaluate_turkiye_fund_participation", source)
        self.assertNotIn("run_turkiye_fund_refresh", FUND_REPORT.read_text(encoding="utf-8"))
        tefas_calls = []
        kap_calls = []
        with patch(
            "services.official_tefas_product.default_tefas_fund_provider",
            side_effect=lambda *a, **k: tefas_calls.append("tefas") or (_ for _ in ()).throw(AssertionError("tefas")),
        ), patch(
            "services.official_kap_pdr_evidence.load_captured_pdr_holdings",
            side_effect=lambda *a, **k: kap_calls.append("kap") or (_ for _ in ()).throw(AssertionError("kap")),
        ):
            load_turkiye_fund_portfolio_contexts(
                participation_repo=self.part_repo,
                snapshot_repo=self.fi_repo,
                portfolio_view=self.view,
            )
            quote_turkiye_fund_unit_price("AIS", snapshot_repo=self.fi_repo)
            build_nabi_adviser_context(
                "IAT nedir?",
                turkiye_fund_contexts=load_turkiye_fund_portfolio_contexts(
                    participation_repo=self.part_repo,
                    snapshot_repo=self.fi_repo,
                    portfolio_view=self.view,
                ),
            )
            run_turkiye_new_money_uat(
                portfolio_view=self.view,
                policy=_exposure_policy(equity=50, sukuk=40, cash=10),
                contexts=load_turkiye_fund_portfolio_contexts(
                    participation_repo=self.part_repo,
                    snapshot_repo=self.fi_repo,
                ),
                conversion=_fx(),
                price_by_symbol=FROZEN_CAPTURED_UNIT_PRICES,
            )
        self.assertEqual(tefas_calls, [])
        self.assertEqual(kap_calls, [])
        refresh = run_turkiye_fund_refresh(symbols=("IAT",), calculated_at="2026-08-30T21:00:00+00:00")
        self.assertEqual(refresh.symbols, ("IAT",))
        self.assertGreaterEqual(refresh.processed, 1)

    def test_production_io_and_regression(self) -> None:
        source = CLI.read_text(encoding="utf-8")
        self.assertIn("participation_assessment_snapshots", source)
        self.assertIn("security_intelligence_snapshots", source)
        self.assertNotIn("post_transaction", source)
        self.assertNotIn("allocate_new_money", Path("services/turkiye_fund_refresh_orchestrator.py").read_text(encoding="utf-8"))
        sp = default_official_sp_funds_provider()
        tefas = default_tefas_fund_provider()
        for symbol in PILOT_FUND_SYMBOLS:
            self.assertTrue(sp.supports(symbol))
            self.assertFalse(tefas.supports(symbol))
        self.assertEqual(evaluate_spus_unchanged(), (71.41, 65.87, 47.57, 52.79))
        self.assertIn("ASELS", BIST.read_text(encoding="utf-8"))
        self.assertTrue(GOAL.is_file())
        self.assertNotIn("AIS", NEW_MONEY.read_text(encoding="utf-8"))
        self.assertFalse(HybridExposureAllocationPolicy().enabled)
        self.assertEqual(resolve_asset_metadata("SPUS", currency="USD")[0], ASSET_CLASS_ETF)
        self.assertTrue(WEALTH_CORE.is_file())
        self.assertTrue(FX.is_file())
        self.assertTrue(US_SI.is_file())


def evaluate_spus_unchanged() -> tuple[float, float, float, float]:
    from services.fund_intelligence_engine import evaluate_official_fund_intelligence

    return (
        evaluate_official_fund_intelligence("SPUS").score,
        evaluate_official_fund_intelligence("SPSK").score,
        evaluate_official_fund_intelligence("SPRE").score,
        evaluate_official_fund_intelligence("SPWO").score,
    )


if __name__ == "__main__":
    unittest.main()
