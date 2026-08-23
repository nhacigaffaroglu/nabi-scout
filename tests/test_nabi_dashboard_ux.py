from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from components.portfolio_decision_center_ui import (
    HEALTHY_MESSAGE,
    ActionCenterPresentation,
    PresentedAction,
)
from services.candidate_pipeline_presentation import (
    NO_OPPORTUNITY_COPY,
    STAGE_ONBOARDING,
    STAGE_RESEARCH_PENDING,
    classify_candidate_pipeline_stage,
    display_nabi_score,
    is_actionable_opportunity,
    nabi_score_is_displayable,
)
from services.fx_rate_contract import FxConversionResult
from services.nabi_dashboard_presentation import (
    DASHBOARD_TITLE,
    FX_MISSING_COPY,
    FX_STALE_COPY,
    MAX_DASHBOARD_ACTIONS,
    NEW_MONEY_LEAD_TEMPLATE,
    build_nabi_today_dashboard,
    present_current_try_equivalent,
    present_opportunity_section,
    present_priority_section,
    present_wealth_section,
)
from services.total_wealth_service import TotalWealthMetrics
from services.ui_table_headers import COLUMN_LABELS_TR, apply_display_headers, label_for_column
from services.wealth_brief_presentation import (
    BriefGoal,
    BriefHeader,
    BriefNewMoney,
    BriefPerformance,
    BriefPriority,
    WealthBrief,
)
from services.wealth_performance_center_presentation import INSUFFICIENT_COPY

PRES = Path("services/nabi_dashboard_presentation.py")
HOME = Path("components/nabi_home_dashboard.py")
UI = Path("services/ui.py")
DASHBOARD = Path("pages/1_Dashboard.py")
ADAY = Path("pages/_4_Aday_Detayi.py")
ADAY_VISIBLE = Path("pages/4_Aday_Detayi.py")
COMPANY = Path("pages/4_Company_Report.py")
WRITE_TOKENS = (
    "post_transaction",
    "register_asset",
    ".insert(",
    ".upsert(",
    ".delete(",
    "capture_portfolio_snapshot",
    "save_planning_fx_schedule",
    "save_policy",
)
PROVIDER_TOKENS = (
    "FMPClient",
    "fmp_client",
    "openai",
    "SECFinancialClient",
    "AlphaVantage",
    "TwelveData",
    "BorsaIstanbul",
)


def _metrics(total: float = 79613.0, *, partial: bool = False) -> TotalWealthMetrics:
    return TotalWealthMetrics(
        base_currency="USD",
        total_wealth=total,
        invested_assets=total,
        cash=0.0,
        equity=total,
        funds_etfs=0.0,
        other_assets=0.0,
        unconverted_value=0.0,
        unpriced_count=1 if partial else 0,
        participation_covered_pct=100.0,
        research_covered_pct=100.0,
        fx_conversion_coverage_pct=100.0,
        partial_total=partial,
        limitation="1 fiyatlanmamış pozisyon." if partial else "",
    )


def _fx_ok(amount: float, *, stale: bool = False) -> FxConversionResult:
    return FxConversionResult(
        native_amount=amount,
        native_currency="USD",
        converted_amount=amount * 48.1,
        base_currency="TRY",
        rate_used=48.1,
        rate_date="2026-08-22",
        converted=True,
        unavailable=False,
        stale=stale,
        limitation="Kur eski olabilir." if stale else "",
    )


def _fx_missing(amount: float) -> FxConversionResult:
    return FxConversionResult(
        native_amount=amount,
        native_currency="USD",
        converted_amount=None,
        base_currency="TRY",
        rate_used=None,
        rate_date=None,
        converted=False,
        unavailable=True,
        stale=False,
        limitation="USD/TRY kuru bulunamadı; dönüşüm yapılmadı.",
    )


def _candidate(
    symbol: str,
    *,
    decision: str = "GÜÇLÜ ADAY",
    participation: str = "Uygun",
    research: str = "YENI",
    score: float = 82.0,
    price: float | None = 120.0,
    completeness: float | None = 88.0,
    source: str = "scanner",
    thesis: str = "Kaliteli büyüme",
) -> dict:
    return {
        "symbol": symbol,
        "decision": decision,
        "participation_status": participation,
        "research_status": research,
        "nabi_score": score,
        "current_price": price,
        "data_completeness": completeness,
        "data_source": source,
        "main_reason": thesis,
        "last_scanned_at": "2026-08-20T10:00:00+00:00" if completeness is not None else None,
    }


def _action(index: int) -> PresentedAction:
    return PresentedAction(
        id=f"action_{index}",
        category_label="Portföy",
        priority_label="Yüksek",
        priority_tone="warning",
        title=f"Öncelik {index}",
        explanation=f"Açıklama {index}.",
        evidence_lines=(),
        limitation=None,
        direction=None,
        options=("İncele", "Bekle"),
    )


def _presented(*actions: PresentedAction, healthy: bool = False) -> ActionCenterPresentation:
    return ActionCenterPresentation(
        heading="NABI Karar Merkezi",
        healthy=healthy,
        healthy_message=HEALTHY_MESSAGE if healthy else None,
        disclaimer="",
        visible_actions=actions,
        hidden_count=0,
        evidence_summary=(),
        action_ids=tuple(row.id for row in actions),
        status_summary=HEALTHY_MESSAGE if healthy else "konular",
        actionable_count=0 if healthy else len(actions),
        highest_severity_label=None if healthy else "Yüksek",
    )


def _brief(*, return_label: str | None = None, limitation: str | None = None) -> WealthBrief:
    return WealthBrief(
        header=BriefHeader(
            title="Brief",
            current_value_label="$79,613",
            valuation_status="Değerleme tamam",
            valuation_complete=True,
            as_of_label="2026-08-22",
        ),
        today_lines=(),
        priority=BriefPriority(
            healthy=True,
            title=HEALTHY_MESSAGE,
            severity_label=None,
            explanation=HEALTHY_MESSAGE,
            evidence_lines=(),
            options=(),
        ),
        goal=BriefGoal(
            target_label="$1,000,000",
            current_progress="%8",
            projected_wealth_label="$400,000",
            attainment_label="%40",
            configured_monthly_label="60,000 TL",
            required_monthly_label="85,000 TL",
            target_date_alternative="2034",
            status_copy="Mevcut plan 2031 hedefi için yeterli görünmüyor.",
        ),
        new_money=BriefNewMoney(
            amount_label="60,000 TL",
            allocated_label="45,000 TL",
            residual_label="15,000 TL",
            recommendations=(),
            unavailable_reason=None,
        ),
        performance=BriefPerformance(
            period_label="Aylık",
            return_label=return_label,
            best_label="AAPL 2.0%" if return_label else None,
            weakest_label="SPUS -1.0%" if return_label else None,
            limitation=limitation or (None if return_label else INSUFFICIENT_COPY),
        ),
        limitations=(),
        tracking_prestart_copy=None,
    )


def _pi_dashboard():
    holding = SimpleNamespace(
        symbol="AAPL",
        portfolio_weight_pct=22.0,
        total_market_value=17000.0,
    )
    slice_row = SimpleNamespace(label="Hisse", weight_pct=80.0)
    attention = SimpleNamespace(
        title="Tek pozisyon yoğunlaşması",
        severity="high",
        metric_value=22.0,
    )
    return SimpleNamespace(
        consolidated_symbols=(holding,),
        base=SimpleNamespace(asset_class_allocation=(slice_row,)),
        top5_concentration_pct=55.0,
        attention_items=(attention,),
    )


class TurkishHeaderTests(unittest.TestCase):
    def test_canonical_columns_have_turkish_labels(self) -> None:
        expected = {
            "symbol": "Sembol",
            "company_name": "Şirket",
            "asset_type": "Varlık Türü",
            "market": "Piyasa",
            "current_price": "Güncel Fiyat",
            "fair_value": "Adil Değer",
            "discount_to_fair_value": "Adil Değere İskonto",
            "nabi_score": "NABI Score",
            "decision": "Karar",
            "participation_status": "Katılım Durumu",
            "research_status": "Araştırma Durumu",
        }
        for column, label in expected.items():
            self.assertEqual(label_for_column(column), label)
            self.assertEqual(COLUMN_LABELS_TR[column], label)

    def test_dataframe_display_renames_without_touching_source(self) -> None:
        frame = pd.DataFrame([{"symbol": "AAPL", "nabi_score": 80, "decision": "ADAY"}])
        display = apply_display_headers(frame, columns=["symbol", "nabi_score", "decision"])
        self.assertEqual(list(display.columns), ["Sembol", "NABI Score", "Karar"])
        self.assertEqual(list(frame.columns), ["symbol", "nabi_score", "decision"])

    def test_dashboard_uses_display_headers(self) -> None:
        source = Path("components/opportunity_center_ui.py").read_text(encoding="utf-8")
        self.assertIn("apply_display_headers", source)
        self.assertIn("present_candidate_display_row", source)


class CurrentFxWealthTests(unittest.TestCase):
    def test_usd_and_try_from_current_fx(self) -> None:
        fx = MagicMock()
        fx.convert_amount.return_value = _fx_ok(79613)
        view = present_current_try_equivalent(79613, fx)
        self.assertTrue(view.available)
        self.assertAlmostEqual(view.amount or 0, 79613 * 48.1, places=1)
        self.assertEqual(view.label, "₺3.83 Mn")
        fx.convert_amount.assert_called_once()
        kwargs = fx.convert_amount.call_args.kwargs
        self.assertEqual(kwargs["from_currency"], "USD")
        self.assertEqual(kwargs["to_currency"], "TRY")

    def test_planning_fx_not_imported_by_dashboard_presentation(self) -> None:
        source = PRES.read_text(encoding="utf-8")
        self.assertNotIn("wealth_planning_fx", source)
        self.assertNotIn("PlanningFxSchedule", source)
        self.assertNotIn("usdtry_for_year", source)

    def test_missing_current_fx_does_not_fabricate_try(self) -> None:
        fx = MagicMock()
        fx.convert_amount.return_value = _fx_missing(79613)
        view = present_current_try_equivalent(79613, fx)
        self.assertFalse(view.available)
        self.assertIsNone(view.amount)
        self.assertIsNone(view.label)
        self.assertIn("TRY", view.limitation or "")

    def test_stale_current_fx_does_not_fabricate_try(self) -> None:
        fx = MagicMock()
        fx.convert_amount.return_value = _fx_ok(79613, stale=True)
        view = present_current_try_equivalent(79613, fx)
        self.assertFalse(view.available)
        self.assertIsNone(view.amount)
        self.assertEqual(view.limitation, FX_STALE_COPY)

    def test_none_fx_service_does_not_fabricate(self) -> None:
        view = present_current_try_equivalent(79613, None)
        self.assertFalse(view.available)
        self.assertEqual(view.limitation, FX_MISSING_COPY)


class OpportunityEligibilityTests(unittest.TestCase):
    def test_incomplete_candidates_excluded(self) -> None:
        incomplete = _candidate(
            "AA",
            decision="VERİ EKSİK",
            participation="Kontrol Et",
            research="YENI",
            score=31.4,
            completeness=20.0,
            source="universe_expansion",
        )
        self.assertFalse(is_actionable_opportunity(incomplete))
        self.assertFalse(nabi_score_is_displayable(incomplete))
        self.assertIsNone(display_nabi_score(incomplete))
        section = present_opportunity_section([incomplete])
        self.assertEqual(section.rows, ())
        self.assertEqual(section.empty_copy, NO_OPPORTUNITY_COPY)

    def test_strong_and_aday_qualified_included(self) -> None:
        rows = [
            _candidate("MSFT", decision="GÜÇLÜ ADAY", score=88),
            _candidate("AAPL", decision="ADAY", score=70, completeness=75),
        ]
        section = present_opportunity_section(rows)
        self.assertEqual([row.symbol for row in section.rows], ["MSFT", "AAPL"])

    def test_numeric_score_alone_is_not_actionable(self) -> None:
        decoy = _candidate(
            "TRAP",
            decision="VERİ EKSİK",
            participation="Kontrol Et",
            score=91.0,
            completeness=10.0,
        )
        self.assertGreater(float(decoy["nabi_score"]), 80)
        self.assertFalse(is_actionable_opportunity(decoy))
        self.assertIsNone(display_nabi_score(decoy))

    def test_kontrol_et_and_research_incomplete_excluded(self) -> None:
        row = _candidate(
            "META",
            decision="GÜÇLÜ ADAY",
            participation="Kontrol Et",
            research="YENI",
            score=85,
        )
        self.assertFalse(is_actionable_opportunity(row))

    def test_pipeline_stages_distinguish_incomplete(self) -> None:
        onboarding = _candidate(
            "NEW",
            decision="VERİ EKSİK",
            participation="Kontrol Et",
            completeness=None,
            price=None,
            source="universe_expansion",
        )
        onboarding.pop("last_scanned_at")
        self.assertEqual(classify_candidate_pipeline_stage(onboarding), STAGE_ONBOARDING)
        pending = _candidate("NVDA", research="YENI")
        self.assertEqual(classify_candidate_pipeline_stage(pending), STAGE_RESEARCH_PENDING)


class DashboardCompositionTests(unittest.TestCase):
    def test_top_actions_max_three(self) -> None:
        presented = _presented(*[_action(index) for index in range(1, 6)])
        section = present_priority_section(presented)
        self.assertEqual(len(section.items), MAX_DASHBOARD_ACTIONS)
        self.assertEqual([item.title for item in section.items], ["Öncelik 1", "Öncelik 2", "Öncelik 3"])

    def test_healthy_priority_copy(self) -> None:
        section = present_priority_section(_presented(healthy=True))
        self.assertTrue(section.healthy)
        self.assertEqual(section.empty_copy, HEALTHY_MESSAGE)

    def test_performance_insufficient_history(self) -> None:
        fx = MagicMock()
        fx.convert_amount.return_value = _fx_ok(79613)
        brief = _brief(return_label=None, limitation=INSUFFICIENT_COPY)
        today = build_nabi_today_dashboard(
            metrics=_metrics(),
            coverage_pct=100.0,
            fx_service=fx,
            pi_dashboard=_pi_dashboard(),
            brief=brief,
            presented_actions=_presented(healthy=True),
            candidates=[],
        )
        self.assertEqual(today.title, DASHBOARD_TITLE)
        self.assertIsNone(today.wealth.change_label)
        self.assertEqual(today.performance.limitation, INSUFFICIENT_COPY)
        self.assertIn("geçmiş", (today.wealth.limitation or "").casefold())

    def test_new_money_preview_does_not_persist(self) -> None:
        for path in (PRES, HOME):
            source = path.read_text(encoding="utf-8")
            for token in WRITE_TOKENS:
                self.assertNotIn(token, source)
        home = HOME.read_text(encoding="utf-8")
        self.assertIn("compose_wealth_operating_views", home)
        self.assertIn(NEW_MONEY_LEAD_TEMPLATE.split("{")[0], PRES.read_text(encoding="utf-8"))

    def test_wealth_section_keeps_usd_canonical(self) -> None:
        fx = MagicMock()
        fx.convert_amount.return_value = _fx_ok(79613)
        section = present_wealth_section(
            _metrics(),
            coverage_pct=100.0,
            fx_service=fx,
            performance=_brief(return_label="1.2%").performance,
        )
        self.assertEqual(section.usd_label, "$79,613")
        self.assertEqual(section.try_equivalent.label, "₺3.83 Mn")
        self.assertEqual(section.change_label, "Aylık: 1.2%")


class NavigationTests(unittest.TestCase):
    def test_aday_detayi_removed_from_visible_navigation(self) -> None:
        source = UI.read_text(encoding="utf-8")
        self.assertFalse(ADAY_VISIBLE.exists())
        self.assertTrue(ADAY.exists())
        self.assertNotIn("pages/4_Aday_Detayi.py", source)
        self.assertNotIn('label="Aday Detayı"', source)
        self.assertIn("hide_retired_streamlit_pages", source)
        self.assertTrue(ADAY.name.startswith("_"))

    def test_company_report_navigation_remains(self) -> None:
        source = UI.read_text(encoding="utf-8")
        self.assertNotIn('st.page_link("pages/4_Company_Report.py"', source)
        self.assertTrue(COMPANY.exists())
        redirect = ADAY.read_text(encoding="utf-8")
        self.assertIn("pages/4_Company_Report.py", redirect)
        firsatlar = Path("services/opportunity_center_presentation.py").read_text(encoding="utf-8")
        self.assertIn("pages/4_Company_Report.py", firsatlar)
        self.assertIn("Şirketi İncele", firsatlar)
        self.assertIn("COMPANY_REPORT_PAGE", Path("components/opportunity_center_ui.py").read_text(encoding="utf-8"))

    def test_no_provider_calls_in_presentation(self) -> None:
        source = PRES.read_text(encoding="utf-8")
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
