from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.portfolio_allocation_center_ui import (
    APPLIED_WEIGHTS_KEY as ASSET_APPLIED_KEY,
    BUCKET_LABELS,
    build_allocation_for_ui,
    flatten_allocation_text,
    present_allocation_center,
    render_portfolio_allocation_center,
)
from components.portfolio_economic_exposure_ui import (
    APPLIED_WEIGHTS_KEY,
    CLASSIFICATION_COVERAGE_LABEL,
    DIMENSION_LABELS,
    DIMENSION_VIEW_KEY,
    EXPOSURE_BUCKET_LABELS,
    GROWTH_ECONOMIC_EXPOSURE_WEIGHTS,
    GROWTH_TARGET_LABEL,
    INCOMPLETE_DRIFT_NOTE,
    OVERRIDE_KEY,
    UNKNOWN_ETF_HEADING,
    UNKNOWN_EVIDENCE,
    USER_CONFIRMED_LABEL,
    VALUATION_COVERAGE_LABEL,
    VIEW_ASSET_CLASS,
    VIEW_ECONOMIC_EXPOSURE,
    apply_exposure_targets_to_session,
    build_economic_exposure_for_ui,
    build_exposure_allocation_for_ui,
    flatten_economic_exposure_text,
    growth_economic_exposure_policy,
    load_persisted_fund_snapshots,
    overrides_from_session,
    policy_from_exposure_weights,
    present_economic_exposure_center,
    save_economic_exposure_policy_from_session,
    set_session_override,
    validate_exposure_target_weights,
)
from services.fund_intelligence_contract import FundHoldingRow, FundHoldingsSnapshotView
from services.portfolio_allocation_intelligence import (
    AllocationDimension,
    AllocationPolicy,
    AllocationProvenance,
    AllocationTarget,
    RoutingStatus,
    build_allocation_intelligence,
)
from services.portfolio_economic_exposure import (
    EconomicExposure,
    ExposureEvidenceSource,
    build_economic_exposure,
)
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_contract import WealthValidationError
from tests.test_portfolio_allocation_center_ui import _live_like_view, _policy_70_30
from tests.test_portfolio_allocation_intelligence import _complete_usd_view, _row
from tests.test_portfolio_economic_exposure import _etf, _equity, _snapshot, _view_from_rows


UI = Path("components/portfolio_economic_exposure_ui.py")
ALLOC_UI = Path("components/portfolio_allocation_center_ui.py")
ENGINE = Path("services/portfolio_economic_exposure.py")
ALLOCATION = Path("services/portfolio_allocation_intelligence.py")
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "fx_rate_refresh",
    "fund_holdings_refresh",
    "FundHoldingsRefreshService",
)
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    ".update(",
)


def _unpriced_tr(symbol: str) -> PositionValuationRow:
    return PositionValuationRow(
        position_id=f"p-{symbol}",
        account_id="acc-1",
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class="equity",
        account_name="Broker",
        quantity=1,
        average_cost=10,
        valuation_currency="TRY",
        price=None,
        price_available=False,
        market_value=None,
        cost_basis=10,
        unrealized_pl=None,
        weight_pct=None,
        is_cash=False,
        included_in_base_totals=False,
    )


def _four_etf_view() -> PortfolioIntelligenceView:
    priced = [
        _equity("AAPL", 40.0),
        _etf("SPUS", 15.0),
        _etf("SPSK", 15.0),
        _etf("SPRE", 15.0),
        _etf("SPWO", 15.0),
    ]
    foreign = [_unpriced_tr("BIMAS"), _unpriced_tr("ASELS"), _unpriced_tr("TUPRS")]
    total = 100.0
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=total,
        priced_total_cost_basis=50,
        priced_total_unrealized_pl=50,
        priced_position_count=5,
        unpriced_position_count=3,
        foreign_currency_position_count=3,
        total_position_count=8,
        mixed_currency_warning=True,
        fx_supported=False,
        priced_positions=priced,
        unpriced_positions=foreign,
        foreign_currency_positions=foreign,
        asset_class_allocation=[AllocationSlice("equity", "equity", 40.0, 40.0)],
        account_allocation=[AllocationSlice("acc-1", "Broker", total, 100.0)],
        health=PortfolioHealthMetrics(40.0, 70.0, 40.0, 0.0, 100.0, 62.5),
        valuation_errors=[],
        price_provider="none",
        unique_price_symbols_fetched=0,
    )


def _cash_equity_view() -> PortfolioIntelligenceView:
    return _view_from_rows(
        [
            _equity("AAPL", 70.0),
            _row(
                symbol="CASH",
                price_available=True,
                market_value=30.0,
                currency="USD",
                weight_pct=30.0,
                asset_class="cash",
            ),
        ]
    )


def _exposure_target_session(*, equity: float = 70.0, cash: float = 30.0) -> dict:
    weights = {
        "equity": equity,
        "fixed_income": 0.0,
        "sukuk": 0.0,
        "real_estate": 0.0,
        "cash": cash,
        "commodity": 0.0,
        "other": 0.0,
    }
    session = {APPLIED_WEIGHTS_KEY: dict(weights)}
    for bucket, value in weights.items():
        session[f"portfolio_economic_exposure_draft_{bucket}"] = value
    return session


def _lookthrough_70_30(symbol: str = "SPUS") -> dict:
    return {
        symbol: _snapshot(
            symbol,
            (
                FundHoldingRow("AAPL", "Apple", 70.0, "equity", None, None),
                FundHoldingRow("CASH", "Cash", 30.0, "cash", None, None),
            ),
        )
    }


class _FakeSt:
    def __init__(self, session_state: dict):
        self.session_state = session_state
        self.recorded: list[str] = []

    def radio(self, *a, **k):
        options = k.get("options") or (a[1] if len(a) > 1 else [VIEW_ASSET_CLASS])
        key = k.get("key")
        if key in self.session_state:
            return self.session_state[key]
        return options[0]

    def columns(self, n, **_k):
        count = n if isinstance(n, int) else len(n)
        return [self for _ in range(count)]

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def number_input(self, *a, **k):
        return 0

    def button(self, *a, **k):
        return False

    def markdown(self, message, **_k):
        self.recorded.append(str(message))

    def caption(self, message, **_k):
        self.recorded.append(str(message))

    def info(self, message, **_k):
        self.recorded.append(str(message))

    def selectbox(self, *a, **k):
        options = k.get("options") or ["USD"]
        return options[0]

    def altair_chart(self, *a, **k):
        return None

    def rerun(self):
        return None


class DimensionSwitchTests(unittest.TestCase):
    def test_dimension_switch_renders_both_views(self) -> None:
        source = ALLOC_UI.read_text(encoding="utf-8")
        self.assertIn("Dağılım görünümü", source)
        self.assertIn(VIEW_ASSET_CLASS, UI.read_text(encoding="utf-8"))
        self.assertIn("Varlık Türü", UI.read_text(encoding="utf-8"))
        self.assertIn("Ekonomik Maruziyet", UI.read_text(encoding="utf-8"))
        view = _four_etf_view()
        asset_state = {DIMENSION_VIEW_KEY: VIEW_ASSET_CLASS, **_policy_70_30()}
        fake_asset = _FakeSt(asset_state)
        with patch.dict("sys.modules", {"streamlit": fake_asset}), patch(
            "components.nabi_design_system._st", return_value=fake_asset
        ):
            asset_presented = render_portfolio_allocation_center(
                portfolio_view=view,
                allocation=build_allocation_intelligence(view),
                session_state=asset_state,
            )
        self.assertIsNotNone(asset_presented)
        asset_text = flatten_allocation_text(asset_presented)
        self.assertIn("ETF", asset_text)
        self.assertEqual(BUCKET_LABELS["etf"], "ETF")

        econ_state = {DIMENSION_VIEW_KEY: VIEW_ECONOMIC_EXPOSURE}
        fake_econ = _FakeSt(econ_state)
        with patch.dict("sys.modules", {"streamlit": fake_econ}), patch(
            "components.nabi_design_system._st", return_value=fake_econ
        ):
            econ_presented = render_portfolio_allocation_center(
                portfolio_view=view,
                session_state=econ_state,
            )
        self.assertIsNotNone(econ_presented)
        text = flatten_economic_exposure_text(econ_presented)
        self.assertIn(DIMENSION_LABELS[VIEW_ASSET_CLASS], text)
        self.assertIn(DIMENSION_LABELS[VIEW_ECONOMIC_EXPOSURE], text)
        self.assertIn("Hisse", text)
        self.assertIn("Bilinmiyor", text)

    def test_asset_class_view_unchanged(self) -> None:
        presented = present_allocation_center(
            build_allocation_for_ui(_live_like_view(), session_state=_policy_70_30()),
            draft_weights=_policy_70_30()[ASSET_APPLIED_KEY],
        )
        text = flatten_allocation_text(presented)
        self.assertIn("ETF", text)
        self.assertIn("Sukuk / Sabit Getirili", text)
        self.assertEqual(BUCKET_LABELS["sukuk"], "Sukuk / Sabit Getirili")
        self.assertEqual(EXPOSURE_BUCKET_LABELS["sukuk"], "Sukuk")
        self.assertNotIn("Bilinmiyor", text)


class CoverageAndUnknownTests(unittest.TestCase):
    def test_turkish_labels_and_separate_coverage(self) -> None:
        exposure = build_economic_exposure(_four_etf_view())
        allocation = build_exposure_allocation_for_ui(_four_etf_view(), exposure, session_state={})
        presented = present_economic_exposure_center(exposure, allocation)
        self.assertEqual(EXPOSURE_BUCKET_LABELS["equity"], "Hisse")
        self.assertEqual(EXPOSURE_BUCKET_LABELS["fixed_income"], "Sabit Getirili")
        self.assertEqual(EXPOSURE_BUCKET_LABELS["sukuk"], "Sukuk")
        self.assertEqual(EXPOSURE_BUCKET_LABELS["real_estate"], "Gayrimenkul")
        self.assertEqual(EXPOSURE_BUCKET_LABELS["cash"], "Nakit")
        self.assertEqual(EXPOSURE_BUCKET_LABELS["commodity"], "Emtia")
        self.assertEqual(EXPOSURE_BUCKET_LABELS["other"], "Diğer")
        self.assertEqual(EXPOSURE_BUCKET_LABELS["unknown"], "Bilinmiyor")
        text = flatten_economic_exposure_text(presented)
        self.assertIn(VALUATION_COVERAGE_LABEL, text)
        self.assertIn(CLASSIFICATION_COVERAGE_LABEL, text)
        self.assertNotEqual(presented.valuation_coverage_pct, presented.classification_coverage_pct)
        self.assertAlmostEqual(presented.valuation_coverage_pct, 62.5, places=1)
        self.assertAlmostEqual(presented.classification_coverage_pct, 40.0, places=1)
        self.assertIn("Bilinmiyor", text)

    def test_unknown_etfs_without_evidence_or_guessing(self) -> None:
        exposure = build_economic_exposure(_four_etf_view())
        allocation = build_exposure_allocation_for_ui(_four_etf_view(), exposure, session_state={})
        presented = present_economic_exposure_center(exposure, allocation)
        text = flatten_economic_exposure_text(presented)
        self.assertIn(UNKNOWN_ETF_HEADING, text)
        by_symbol = {row.symbol: row for row in presented.unknown_etfs}
        for symbol in ("SPUS", "SPSK", "SPRE", "SPWO"):
            row = by_symbol[symbol]
            self.assertEqual(row.instrument_class, "ETF")
            self.assertEqual(row.economic_exposure, "Bilinmiyor")
            self.assertEqual(row.evidence, UNKNOWN_EVIDENCE)
        self.assertNotIn("SPUS = Equity", text)
        self.assertNotIn("SPSK = Sukuk", text)
        self.assertNotIn("SPRE = Real Estate", text)
        self.assertNotIn("SPWO = Equity", text)
        aapl = next(row for row in presented.instruments if row.symbol == "AAPL")
        self.assertIn("Hisse", aapl.slice_text)
        self.assertEqual(aapl.evidence, "asset-class fallback")
        equity = next(row for row in presented.buckets if row.bucket_id == "equity")
        self.assertTrue({"BIMAS", "ASELS", "TUPRS"} <= set(equity.unpriced_symbols))


class OverrideAndMultiExposureTests(unittest.TestCase):
    def test_user_override_is_session_only_and_highest_precedence(self) -> None:
        state: dict = {}
        error = set_session_override(state, "SPSK", "sukuk")
        self.assertIsNone(error)
        self.assertEqual(state[OVERRIDE_KEY]["SPSK"], "sukuk")
        self.assertIsNotNone(set_session_override(state, "SPUS", "unknown"))
        mappings = overrides_from_session(state)
        self.assertEqual(mappings["SPSK"][0].evidence_source, ExposureEvidenceSource.USER_CONFIRMED)
        view = build_economic_exposure_for_ui(
            _four_etf_view(),
            session_state=state,
            fund_snapshots={
                "SPSK": _snapshot(
                    "SPSK",
                    (FundHoldingRow("AAPL", "Apple", 100.0, "equity", None, None),),
                )
            },
        )
        spsk = next(row for row in view.instruments if row.symbol == "SPSK")
        self.assertEqual(spsk.economic_exposures[0].exposure_bucket, "sukuk")
        self.assertEqual(spsk.economic_exposures[0].evidence_source, ExposureEvidenceSource.USER_CONFIRMED)
        presented = present_economic_exposure_center(
            view,
            build_exposure_allocation_for_ui(_four_etf_view(), view, session_state=state),
        )
        self.assertIn(USER_CONFIRMED_LABEL, flatten_economic_exposure_text(presented))
        ui = UI.read_text(encoding="utf-8")
        self.assertIn("Oturumda kalır; kaydedilmez.", ui)
        self.assertIn(OVERRIDE_KEY, ui)

    def test_multi_exposure_rendering_not_aggressively_rounded(self) -> None:
        snapshots = _lookthrough_70_30("SPUS")
        exposure = build_economic_exposure(_view_from_rows([_etf("SPUS", 100.0)]), fund_snapshots=snapshots)
        presented = present_economic_exposure_center(
            exposure,
            build_exposure_allocation_for_ui(
                _view_from_rows([_etf("SPUS", 100.0)]),
                exposure,
                session_state={},
            ),
        )
        spus = next(row for row in presented.instruments if row.symbol == "SPUS")
        self.assertIn("70% Hisse", spus.slice_text)
        self.assertIn("30% Nakit", spus.slice_text)
        self.assertEqual(sum(item.weight_pct for item in spus.slices), 100.0)


class TargetAndRoutingTests(unittest.TestCase):
    def test_economic_exposure_target_validation(self) -> None:
        valid = {
            "equity": 55.0,
            "fixed_income": 10.0,
            "sukuk": 10.0,
            "real_estate": 5.0,
            "cash": 10.0,
            "commodity": 5.0,
            "other": 5.0,
        }
        self.assertIsNone(validate_exposure_target_weights(valid))
        policy = policy_from_exposure_weights(valid)
        self.assertIsNotNone(policy)
        assert policy is not None
        self.assertEqual(policy.targets[0].dimension, AllocationDimension.ECONOMIC_EXPOSURE)
        self.assertIsNotNone(validate_exposure_target_weights({**valid, "unknown": 1.0, "other": 4.0}))
        with self.assertRaises(WealthValidationError):
            AllocationTarget("unknown", AllocationDimension.ECONOMIC_EXPOSURE, 100).validate()
        self.assertIsNotNone(
            validate_exposure_target_weights(
                {**valid, "equity": 50.0}
            )
        )
        self.assertIn("otomatik dengeleme yok", validate_exposure_target_weights({**valid, "equity": 50.0}))
        self.assertEqual(
            validate_exposure_target_weights({**valid, "equity": -1.0, "other": 6.0}),
            "Hedef ağırlık negatif olamaz.",
        )
        source = UI.read_text(encoding="utf-8")
        self.assertIn("otomatik dengeleme yok", source)
        self.assertNotIn("def normalize", source)

    def test_session_apply_does_not_persist(self) -> None:
        state = {
            "portfolio_economic_exposure_draft_equity": 70.0,
            "portfolio_economic_exposure_draft_cash": 30.0,
            "portfolio_economic_exposure_draft_fixed_income": 0.0,
            "portfolio_economic_exposure_draft_sukuk": 0.0,
            "portfolio_economic_exposure_draft_real_estate": 0.0,
            "portfolio_economic_exposure_draft_commodity": 0.0,
            "portfolio_economic_exposure_draft_other": 0.0,
        }
        self.assertIsNone(apply_exposure_targets_to_session(state))
        self.assertEqual(state[APPLIED_WEIGHTS_KEY]["equity"], 70.0)

    def test_routing_uses_bucket_only_and_unknown_is_indeterminate(self) -> None:
        clean = _cash_equity_view()
        exposure = build_economic_exposure(clean)
        allocation = build_exposure_allocation_for_ui(
            clean,
            exposure,
            session_state=_exposure_target_session(equity=50.0, cash=50.0)
            | {"portfolio_allocation_contribution_amount": 20, "portfolio_allocation_contribution_currency": "USD"},
        )
        route = allocation.routing[0]
        self.assertEqual(route.status, RoutingStatus.AVAILABLE)
        self.assertEqual(route.best_bucket_id, "cash")
        self.assertNotIn(route.best_bucket_id, {"AAPL", "CASH", "SPUS"})
        presented = present_economic_exposure_center(exposure, allocation)
        self.assertIn("Nakit bölgesine", presented.routing.message)
        self.assertNotIn("Buy", presented.routing.message)
        self.assertNotIn("SPUS", presented.routing.message)

        unknown_view = _complete_usd_view()
        unknown_exposure = build_economic_exposure(unknown_view)
        unknown_alloc = build_exposure_allocation_for_ui(
            unknown_view,
            unknown_exposure,
            session_state=_exposure_target_session(equity=70.0, cash=30.0)
            | {"portfolio_allocation_contribution_amount": 20, "portfolio_allocation_contribution_currency": "USD"},
        )
        unknown_route = unknown_alloc.routing[0]
        self.assertEqual(unknown_route.status, RoutingStatus.INDETERMINATE)
        self.assertIsNone(unknown_route.best_bucket_id)
        self.assertIn("EXPOSURE_CLASSIFICATION_INCOMPLETE", unknown_route.limitations)


class GrowthTargetTests(unittest.TestCase):
    def test_growth_target_contract(self) -> None:
        policy = growth_economic_exposure_policy()
        self.assertEqual(policy.provenance, AllocationProvenance.USER_DEFINED)
        self.assertTrue(all(row.dimension == AllocationDimension.ECONOMIC_EXPOSURE for row in policy.targets))
        weights = {row.bucket_id: row.target_weight_pct for row in policy.targets}
        self.assertEqual(weights["equity"], 75.0)
        self.assertEqual(weights["sukuk"], 10.0)
        self.assertEqual(weights["fixed_income"], 5.0)
        self.assertEqual(weights["real_estate"], 5.0)
        self.assertEqual(weights["cash"], 5.0)
        self.assertEqual(weights["commodity"], 0.0)
        self.assertEqual(weights["other"], 0.0)
        self.assertAlmostEqual(sum(GROWTH_ECONOMIC_EXPOSURE_WEIGHTS.values()), 100.0)
        self.assertNotIn("unknown", weights)
        self.assertNotIn("etf", weights)
        self.assertNotIn("35% ETF", UI.read_text(encoding="utf-8"))
        session = {
            f"portfolio_economic_exposure_draft_{bucket}": value
            for bucket, value in GROWTH_ECONOMIC_EXPOSURE_WEIGHTS.items()
        }
        service = MagicMock()
        service.save_policy.return_value = policy
        error = save_economic_exposure_policy_from_session(
            session, policy_service=service, portfolio_id="pf-a"
        )
        self.assertIsNone(error)
        service.save_policy.assert_called_once()
        saved = service.save_policy.call_args[0][1]
        self.assertEqual(saved.targets[0].dimension, AllocationDimension.ECONOMIC_EXPOSURE)

    def test_growth_label_and_indeterminate_copy(self) -> None:
        view = _four_etf_view()
        exposure = build_economic_exposure(view)
        session = {
            APPLIED_WEIGHTS_KEY: dict(GROWTH_ECONOMIC_EXPOSURE_WEIGHTS),
            **{
                f"portfolio_economic_exposure_draft_{bucket}": value
                for bucket, value in GROWTH_ECONOMIC_EXPOSURE_WEIGHTS.items()
            },
        }
        allocation = build_exposure_allocation_for_ui(view, exposure, session_state=session)
        presented = present_economic_exposure_center(
            exposure,
            allocation,
            draft_weights=GROWTH_ECONOMIC_EXPOSURE_WEIGHTS,
            persisted=True,
        )
        text = flatten_economic_exposure_text(presented)
        self.assertIn(GROWTH_TARGET_LABEL, text)
        self.assertIn(INCOMPLETE_DRIFT_NOTE, text)
        statuses = {row.bucket_id: row for row in presented.buckets}
        self.assertTrue(statuses["sukuk"].indeterminate)
        self.assertNotIn("Buy", text)
        self.assertNotIn("SPUS = Equity", text)
        self.assertNotEqual(presented.routing.status, RoutingStatus.AVAILABLE.value)
        self.assertIsNone(presented.routing.best_bucket_label)


class SafetyTests(unittest.TestCase):
    def test_no_provider_calls_or_live_writes_in_ui(self) -> None:
        for path in (UI, ALLOC_UI, ENGINE):
            raw = path.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                self.assertNotIn(token, raw)
        for token in WRITE_TOKENS:
            self.assertNotIn(token, UI.read_text(encoding="utf-8"))
        wealth = MagicMock()
        wealth.client = object()
        with patch(
            "services.fund_holdings_service.FundHoldingsService.get_snapshot",
            return_value=None,
        ) as get_snapshot, patch(
            "services.fund_holdings_refresh_service.FundHoldingsRefreshService"
        ) as refresh:
            load_persisted_fund_snapshots(wealth, ("SPUS",))
            get_snapshot.assert_called_once_with("SPUS")
            refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
