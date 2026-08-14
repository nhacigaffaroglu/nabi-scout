import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from services.nabi_intelligence_facade import InvestmentIntelligenceView
from services.portfolio_intelligence_contract import (
    AllocationSlice,
    PortfolioHealthMetrics,
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_adviser_contract import (
    ADVISER_SCHEMA_VERSION,
    PROHIBITED_CLAIMS,
)
from services.wealth_adviser_grounding import (
    CATEGORY_ADJUSTMENT,
    CONFIDENCE_ADJUSTMENT,
    MAX_USER_QUESTIONS,
    SEVERITY_BASE_SCORE,
    build_adviser_brief,
    build_adviser_context,
    build_portfolio_facts,
    build_questions,
    diagnostic_to_finding,
    priority_score_for_diagnostic,
)
from services.wealth_adviser_service import WealthAdviserService
from services.wealth_diagnostics_contract import (
    DiagnosticCategory,
    DiagnosticConfidence,
    DiagnosticSeverity,
    PortfolioDiagnostic,
)
from services.wealth_diagnostics_engine import build_portfolio_diagnostics
from services.wealth_timeline_contract import (
    BenchmarkComparisonView,
    PortfolioHistoryPoint,
    PortfolioLinkedPerformance,
    WealthPerformanceView,
)


def _position(
    *,
    symbol: str,
    weight_pct: float,
    market_value: float,
    unrealized_pl: float = 0.0,
    is_cash: bool = False,
    asset_class: str = "equity",
    nabi=None,
) -> PositionValuationRow:
    return PositionValuationRow(
        position_id=f"p-{symbol}",
        account_id="a1",
        asset_id=f"as-{symbol}",
        symbol=symbol,
        asset_class=asset_class,
        account_name="Broker",
        quantity=1,
        average_cost=market_value,
        valuation_currency="USD",
        price=market_value,
        price_available=True,
        market_value=market_value,
        cost_basis=market_value - unrealized_pl,
        unrealized_pl=unrealized_pl,
        weight_pct=weight_pct,
        is_cash=is_cash,
        included_in_base_totals=True,
        nabi=nabi,
    )


def _view(
    *,
    positions: list[PositionValuationRow],
    health: PortfolioHealthMetrics,
    unpriced: int = 0,
    mixed: bool = False,
    foreign: int = 0,
    unpriced_positions: list | None = None,
    foreign_positions: list | None = None,
) -> PortfolioIntelligenceView:
    priced_total = sum(row.market_value or 0.0 for row in positions)
    return PortfolioIntelligenceView(
        portfolio_id="pf-1",
        portfolio_name="Main",
        base_currency="USD",
        priced_total_market_value=priced_total,
        priced_total_cost_basis=priced_total,
        priced_total_unrealized_pl=0.0,
        priced_position_count=len(positions),
        unpriced_position_count=unpriced,
        foreign_currency_position_count=foreign,
        total_position_count=len(positions) + unpriced,
        mixed_currency_warning=mixed,
        fx_supported=False,
        priced_positions=positions,
        unpriced_positions=unpriced_positions or [],
        foreign_currency_positions=foreign_positions or [],
        asset_class_allocation=[
            AllocationSlice(key="equity", label="equity", market_value=priced_total, weight_pct=100.0)
        ],
        account_allocation=[],
        health=health,
        valuation_errors=[],
        price_provider="fmp",
        unique_price_symbols_fetched=0,
    )


def _full_health(**overrides) -> PortfolioHealthMetrics:
    defaults = dict(
        largest_position_weight_pct=25.0,
        top3_concentration_pct=65.0,
        largest_asset_class_concentration_pct=65.0,
        cash_pct=50.0,
        invested_pct=50.0,
        priced_position_coverage_pct=100.0,
    )
    defaults.update(overrides)
    return PortfolioHealthMetrics(**defaults)


def _diagnostics(
    portfolio_view: PortfolioIntelligenceView,
    *,
    performance_view=None,
    benchmark_view=None,
    transaction_history_complete: bool = True,
):
    return build_portfolio_diagnostics(
        portfolio_id="pf-1",
        generated_at="2026-08-13T00:00:00+00:00",
        portfolio_view=portfolio_view,
        performance_view=performance_view,
        benchmark_view=benchmark_view,
        transaction_history_complete=transaction_history_complete,
    )


class WealthAdviserContractTests(unittest.TestCase):
    def test_schema_version_stable(self) -> None:
        self.assertEqual(ADVISER_SCHEMA_VERSION, "wealth-adviser-v3")

    def test_prohibited_claims_present(self) -> None:
        self.assertGreaterEqual(len(PROHIBITED_CLAIMS), 8)
        self.assertIn("Do not override deterministic calculations.", PROHIBITED_CLAIMS)


class WealthAdviserGroundingTests(unittest.TestCase):
    def test_portfolio_facts_copied_from_intelligence_view(self) -> None:
        view = _view(
            positions=[
                _position(symbol="AAPL", weight_pct=60.0, market_value=6000),
                _position(symbol="MSFT", weight_pct=40.0, market_value=4000),
            ],
            health=_full_health(
                largest_position_weight_pct=60.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        diagnostics = _diagnostics(view)
        facts = build_portfolio_facts(view, diagnostics_view=diagnostics)
        self.assertEqual(facts.portfolio_id, "pf-1")
        self.assertEqual(facts.priced_market_value, 10000.0)
        self.assertEqual(facts.largest_position_pct, 60.0)
        self.assertFalse(facts.performance_comparable)
        self.assertFalse(facts.benchmark_available)

    def test_optional_performance_and_benchmark_copied_only_when_comparable(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        perf = WealthPerformanceView(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            history_points=[],
            linked_performance=PortfolioLinkedPerformance(
                period_start_at="t1",
                period_end_at="t2",
                base_currency="USD",
                subperiod_count=1,
                linked_return_pct=8.5,
                performance_comparable=True,
                warnings=[],
                subperiods=[],
            ),
        )
        benchmark = BenchmarkComparisonView(
            benchmark_symbol="SPY",
            portfolio_normalized=[],
            portfolio_return_pct=5.0,
            benchmark_return_pct=10.0,
            relative_return_pct=-5.0,
            performance_comparable=True,
            warnings=[],
            provider_fetch_count=1,
        )
        diagnostics = _diagnostics(view, performance_view=perf, benchmark_view=benchmark)
        facts = build_portfolio_facts(
            view,
            performance_view=perf,
            benchmark_view=benchmark,
            diagnostics_view=diagnostics,
        )
        self.assertEqual(facts.linked_return_pct, 8.5)
        self.assertEqual(facts.benchmark_return_pct, 10.0)
        self.assertEqual(facts.relative_return_pct, -5.0)
        self.assertTrue(facts.performance_comparable)
        self.assertTrue(facts.benchmark_available)

    def test_context_serialization_json_safe_and_stable(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        diagnostics = _diagnostics(view)
        kwargs = dict(
            portfolio_view=view,
            diagnostics_view=diagnostics,
            generated_from_snapshot_count=0,
        )
        first = json.dumps(build_adviser_context(**kwargs).to_dict(), sort_keys=True)
        second = json.dumps(build_adviser_context(**kwargs).to_dict(), sort_keys=True)
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertEqual(parsed["schema_version"], ADVISER_SCHEMA_VERSION)
        self.assertTrue(parsed["deterministic_only"])

    def test_priority_high_over_watch_over_info(self) -> None:
        high = PortfolioDiagnostic(
            code="A",
            category=DiagnosticCategory.CONCENTRATION,
            severity=DiagnosticSeverity.HIGH,
            title="H",
            summary="H",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="x",
        )
        watch = PortfolioDiagnostic(
            code="B",
            category=DiagnosticCategory.CONCENTRATION,
            severity=DiagnosticSeverity.WATCH,
            title="W",
            summary="W",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="x",
        )
        info = PortfolioDiagnostic(
            code="C",
            category=DiagnosticCategory.CONCENTRATION,
            severity=DiagnosticSeverity.INFO,
            title="I",
            summary="I",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="x",
        )
        self.assertGreater(priority_score_for_diagnostic(high), priority_score_for_diagnostic(watch))
        self.assertGreater(priority_score_for_diagnostic(watch), priority_score_for_diagnostic(info))

    def test_priority_confidence_and_category_tie_break(self) -> None:
        high_conf = PortfolioDiagnostic(
            code="SAME",
            category=DiagnosticCategory.CASH,
            severity=DiagnosticSeverity.WATCH,
            title="t",
            summary="s",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="x",
        )
        low_conf = PortfolioDiagnostic(
            code="SAME",
            category=DiagnosticCategory.CASH,
            severity=DiagnosticSeverity.WATCH,
            title="t",
            summary="s",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.LOW,
            source="x",
        )
        self.assertGreater(
            priority_score_for_diagnostic(high_conf),
            priority_score_for_diagnostic(low_conf),
        )
        data_quality = PortfolioDiagnostic(
            code="DATA",
            category=DiagnosticCategory.DATA_QUALITY,
            severity=DiagnosticSeverity.WATCH,
            title="d",
            summary="d",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="x",
        )
        concentration = PortfolioDiagnostic(
            code="CONC",
            category=DiagnosticCategory.CONCENTRATION,
            severity=DiagnosticSeverity.WATCH,
            title="c",
            summary="c",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="x",
        )
        self.assertGreater(
            priority_score_for_diagnostic(data_quality),
            priority_score_for_diagnostic(concentration),
        )

    def test_data_quality_finding_outranks_concentration_at_same_severity(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=75.0,
            ),
            unpriced=1,
            unpriced_positions=[_position(symbol="MSFT", weight_pct=0.0, market_value=0.0)],
        )
        context = build_adviser_context(
            portfolio_view=view,
            diagnostics_view=_diagnostics(view),
        )
        self.assertFalse(context.data_quality.valuation_complete)
        top = context.findings[0]
        self.assertEqual(top.category, DiagnosticCategory.DATA_QUALITY.value)
        self.assertTrue(context.data_quality.warnings)

    def test_partial_data_limitations_on_structural_findings(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=50.0,
            ),
            unpriced=1,
            unpriced_positions=[_position(symbol="MSFT", weight_pct=0.0, market_value=0.0)],
        )
        context = build_adviser_context(
            portfolio_view=view,
            diagnostics_view=_diagnostics(view),
        )
        concentration = next(
            (item for item in context.findings if item.category == DiagnosticCategory.CONCENTRATION.value),
            None,
        )
        self.assertIsNone(concentration)
        self.assertFalse(context.data_quality.valuation_complete)

    def test_mixed_currency_warning_present(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
            mixed=True,
        )
        context = build_adviser_context(
            portfolio_view=view,
            diagnostics_view=_diagnostics(view),
        )
        self.assertTrue(context.data_quality.mixed_currency)
        self.assertTrue(any("baz para birimi" in item.lower() for item in context.data_quality.warnings))

    def test_performance_not_comparable_limits_interpretation(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        context = build_adviser_context(
            portfolio_view=view,
            diagnostics_view=_diagnostics(view),
        )
        self.assertFalse(context.data_quality.performance_comparable)
        brief = build_adviser_brief(context)
        self.assertTrue(
            any("performans" in note.lower() for note in brief.data_quality_notes)
            or any("benchmark" in note.lower() for note in brief.data_quality_notes)
        )

    def test_benchmark_unavailable_no_fabricated_relative_return(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        context = build_adviser_context(
            portfolio_view=view,
            diagnostics_view=_diagnostics(view, benchmark_view=None),
        )
        self.assertIsNone(context.portfolio.relative_return_pct)
        self.assertFalse(context.portfolio.benchmark_available)

    def test_nabi_invariance_financial_facts_and_findings(self) -> None:
        base_positions = [
            _position(symbol="AAPL", weight_pct=60.0, market_value=6000),
            _position(symbol="MSFT", weight_pct=40.0, market_value=4000),
        ]
        health = _full_health(
            largest_position_weight_pct=60.0,
            top3_concentration_pct=100.0,
            largest_asset_class_concentration_pct=100.0,
            cash_pct=0.0,
            invested_pct=100.0,
        )
        nabi_high = InvestmentIntelligenceView(
            symbol="X",
            market="NASDAQ",
            company_name="X",
            decision="BUY",
            nabi_score=95.0,
            participation_status=None,
            participation_score=None,
            research_status="ready",
            candidate_id="c1",
            has_candidate=True,
            has_participation_snapshot=False,
        )
        nabi_low = InvestmentIntelligenceView(
            symbol="X",
            market="NASDAQ",
            company_name="X",
            decision="AVOID",
            nabi_score=10.0,
            participation_status=None,
            participation_score=None,
            research_status="ready",
            candidate_id="c1",
            has_candidate=True,
            has_participation_snapshot=False,
        )

        def _context(positions):
            view = _view(positions=positions, health=health)
            return build_adviser_context(
                portfolio_view=view,
                diagnostics_view=_diagnostics(view),
            )

        no_nabi = _context(base_positions)
        high_nabi = _context(
            [
                _position(symbol="AAPL", weight_pct=60.0, market_value=6000, nabi=nabi_high),
                _position(symbol="MSFT", weight_pct=40.0, market_value=4000, nabi=nabi_high),
            ]
        )
        low_nabi = _context(
            [
                _position(symbol="AAPL", weight_pct=60.0, market_value=6000, nabi=nabi_low),
                _position(symbol="MSFT", weight_pct=40.0, market_value=4000, nabi=nabi_low),
            ]
        )

        self.assertEqual(no_nabi.portfolio.to_dict(), high_nabi.portfolio.to_dict())
        self.assertEqual(no_nabi.portfolio.to_dict(), low_nabi.portfolio.to_dict())

        def _financial_key(item):
            return (
                item.diagnostic_code,
                item.severity,
                item.confidence,
                item.statement,
                tuple(sorted(item.evidence.items())),
                item.priority_score,
            )

        fin_no = [_financial_key(item) for item in no_nabi.findings if item.category != "NABI_CONTEXT"]
        fin_high = [_financial_key(item) for item in high_nabi.findings if item.category != "NABI_CONTEXT"]
        fin_low = [_financial_key(item) for item in low_nabi.findings if item.category != "NABI_CONTEXT"]
        self.assertEqual(fin_no, fin_high)
        self.assertEqual(fin_no, fin_low)

    def test_questions_deterministic_deduped_and_capped(self) -> None:
        view = _view(
            positions=[
                _position(symbol="CASH", weight_pct=85.0, market_value=8500, is_cash=True, asset_class="cash"),
                _position(symbol="AAPL", weight_pct=15.0, market_value=1500),
            ],
            health=_full_health(
                largest_position_weight_pct=85.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=85.0,
                cash_pct=85.0,
                invested_pct=15.0,
            ),
        )
        context = build_adviser_context(
            portfolio_view=view,
            diagnostics_view=_diagnostics(view),
        )
        questions = build_questions(context.findings)
        self.assertLessEqual(len(questions), MAX_USER_QUESTIONS)
        self.assertEqual(len(questions), len(set(questions)))
        self.assertIn("Bu yoğunlaşma bilinçli bir tercih mi?", questions)

    def test_brief_includes_prohibited_claims(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        brief = build_adviser_brief(
            build_adviser_context(
                portfolio_view=view,
                diagnostics_view=_diagnostics(view),
            )
        )
        self.assertEqual(brief.prohibited_claims, PROHIBITED_CLAIMS)
        self.assertTrue(brief.headline)
        self.assertTrue(brief.portfolio_summary)
        self.assertLessEqual(len(brief.top_findings), 3)

    def test_priority_constants_explicit(self) -> None:
        self.assertEqual(SEVERITY_BASE_SCORE[DiagnosticSeverity.HIGH], 300)
        self.assertEqual(CONFIDENCE_ADJUSTMENT[DiagnosticConfidence.HIGH], 30)
        self.assertGreater(
            CATEGORY_ADJUSTMENT[DiagnosticCategory.DATA_QUALITY],
            CATEGORY_ADJUSTMENT[DiagnosticCategory.NABI_CONTEXT],
        )


class WealthAdviserServiceTests(unittest.TestCase):
    def test_service_builds_from_prebuilt_views_without_side_effects(self) -> None:
        service = WealthAdviserService()
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        diagnostics = _diagnostics(view)
        context, brief = service.build_preview(view, diagnostics)
        self.assertEqual(context.schema_version, ADVISER_SCHEMA_VERSION)
        self.assertEqual(brief.context.schema_version, ADVISER_SCHEMA_VERSION)
        self.assertTrue(context.deterministic_only)


class WealthAdviserFirewallTests(unittest.TestCase):
    def test_grounding_has_no_provider_or_db_imports(self) -> None:
        import services.wealth_adviser_grounding as grounding_module

        source = inspect.getsource(grounding_module).lower()
        for banned in [
            "fmp_client",
            "supabase",
            "nabi_score",
            "participation_engine",
            "scanner",
            ".insert(",
            ".update(",
            ".delete(",
        ]:
            self.assertNotIn(banned, source, banned)

    def test_service_has_no_provider_or_db_writes(self) -> None:
        source = inspect.getsource(WealthAdviserService).lower()
        self.assertNotIn("fmp_client", source)
        self.assertNotIn("supabase", source)
        self.assertNotIn(".insert(", source)


class WealthAdviserUiTests(unittest.TestCase):
    @staticmethod
    def _adviser_block() -> str:
        return Path("pages/10_Wealth.py").read_text(encoding="utf-8").split("with tab_adviser:")[1]

    def test_danisman_tab_present(self) -> None:
        source = Path("pages/10_Wealth.py").read_text(encoding="utf-8")
        self.assertIn('"Danışman"', source)
        self.assertIn("tab_adviser", source)

    def test_deterministic_only_caption_visible(self) -> None:
        block = self._adviser_block()
        self.assertIn("deterministik wealth verileri kaynak gerçektir", block.lower())

    def test_no_ai_active_claim(self) -> None:
        block = self._adviser_block().lower()
        self.assertTrue(
            "ai yorumu etkin değil" in block or "yorum katmanıdır" in block
        )

    def test_no_buy_sell_wording(self) -> None:
        block = self._adviser_block().lower()
        for phrase in ["should buy", "should sell", "alım öner", "satım öner", "öneriyorum"]:
            self.assertNotIn(phrase, block)

    def test_technical_context_collapsed(self) -> None:
        block = self._adviser_block()
        self.assertIn("Teknik bağlam", block)
        self.assertIn("to_dict()", block)

    def test_analiz_block_unchanged_marker(self) -> None:
        source = Path("pages/10_Wealth.py").read_text(encoding="utf-8")
        analysis = source.split("with tab_analysis:")[1].split("with tab_adviser:")[0]
        self.assertIn("benchmark_view=None", analysis)
        self.assertIn("_render_diagnostic_card", analysis)
        self.assertIn("Teknik ayrıntılar", source)


class WealthAdviserValidationGateTests(unittest.TestCase):
    def test_portfolio_facts_trace_to_intelligence_view_fields(self) -> None:
        view = _view(
            positions=[
                _position(symbol="AAPL", weight_pct=60.0, market_value=6000, unrealized_pl=100),
                _position(symbol="MSFT", weight_pct=40.0, market_value=4000, unrealized_pl=-50),
            ],
            health=_full_health(
                largest_position_weight_pct=60.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        view = PortfolioIntelligenceView(
            portfolio_id=view.portfolio_id,
            portfolio_name=view.portfolio_name,
            base_currency=view.base_currency,
            priced_total_market_value=12345.67,
            priced_total_cost_basis=12000.0,
            priced_total_unrealized_pl=345.67,
            priced_position_count=view.priced_position_count,
            unpriced_position_count=view.unpriced_position_count,
            foreign_currency_position_count=view.foreign_currency_position_count,
            total_position_count=view.total_position_count,
            mixed_currency_warning=view.mixed_currency_warning,
            fx_supported=view.fx_supported,
            priced_positions=view.priced_positions,
            unpriced_positions=view.unpriced_positions,
            foreign_currency_positions=view.foreign_currency_positions,
            asset_class_allocation=view.asset_class_allocation,
            account_allocation=view.account_allocation,
            health=view.health,
            valuation_errors=view.valuation_errors,
            price_provider=view.price_provider,
            unique_price_symbols_fetched=view.unique_price_symbols_fetched,
        )
        diagnostics = _diagnostics(view)
        facts = build_portfolio_facts(view, diagnostics_view=diagnostics)
        self.assertEqual(facts.priced_market_value, view.priced_total_market_value)
        self.assertEqual(facts.total_cost_basis, view.priced_total_cost_basis)
        self.assertEqual(facts.unrealized_pl, view.priced_total_unrealized_pl)
        self.assertEqual(facts.largest_position_pct, view.health.largest_position_weight_pct)
        self.assertEqual(facts.cash_pct, view.health.cash_pct)
        self.assertEqual(facts.unpriced_position_count, view.unpriced_position_count)

    def test_findings_trace_to_diagnostics_without_mutation(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000, unrealized_pl=-25)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        diagnostics = _diagnostics(view)
        context = build_adviser_context(portfolio_view=view, diagnostics_view=diagnostics)
        diag_by_code = {item.code: item for item in diagnostics.diagnostics}
        for finding in context.findings:
            diagnostic = diag_by_code[finding.diagnostic_code]
            self.assertEqual(finding.statement, diagnostic.summary)
            self.assertEqual(finding.evidence, diagnostic.evidence)
            self.assertEqual(finding.severity, diagnostic.severity.value)
            self.assertEqual(finding.confidence, diagnostic.confidence.value)
            self.assertEqual(finding.source, diagnostic.source)
            self.assertEqual(finding.affected_symbols, tuple(diagnostic.affected_symbols))

    def test_priority_never_mutates_severity_and_info_stays_info(self) -> None:
        data_quality = build_adviser_context(
            portfolio_view=_view(
                positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
                health=_full_health(
                    largest_position_weight_pct=100.0,
                    top3_concentration_pct=100.0,
                    largest_asset_class_concentration_pct=100.0,
                    cash_pct=0.0,
                    invested_pct=100.0,
                ),
            ),
            diagnostics_view=_diagnostics(
                _view(
                    positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
                    health=_full_health(
                        largest_position_weight_pct=100.0,
                        top3_concentration_pct=100.0,
                        largest_asset_class_concentration_pct=100.0,
                        cash_pct=0.0,
                        invested_pct=100.0,
                    ),
                )
            ),
        ).data_quality
        info_diag = PortfolioDiagnostic(
            code="INFO_ONLY",
            category=DiagnosticCategory.PERFORMANCE,
            severity=DiagnosticSeverity.INFO,
            title="info",
            summary="info",
            evidence={"x": 1},
            metric_value=1.0,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="portfolio_intelligence",
        )
        finding = diagnostic_to_finding(info_diag, data_quality=data_quality)
        self.assertEqual(finding.severity, DiagnosticSeverity.INFO.value)
        self.assertGreater(priority_score_for_diagnostic(info_diag), 0)
        self.assertLess(
            priority_score_for_diagnostic(info_diag),
            priority_score_for_diagnostic(
                PortfolioDiagnostic(
                    code="WATCH",
                    category=DiagnosticCategory.PERFORMANCE,
                    severity=DiagnosticSeverity.WATCH,
                    title="w",
                    summary="w",
                    evidence={},
                    metric_value=None,
                    threshold=None,
                    affected_symbols=[],
                    confidence=DiagnosticConfidence.HIGH,
                    source="x",
                )
            ),
        )

    def test_high_low_confidence_ranks_below_high_high_at_same_severity(self) -> None:
        high_high = PortfolioDiagnostic(
            code="HH",
            category=DiagnosticCategory.CONCENTRATION,
            severity=DiagnosticSeverity.HIGH,
            title="hh",
            summary="hh",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="x",
        )
        high_low = PortfolioDiagnostic(
            code="HL",
            category=DiagnosticCategory.CONCENTRATION,
            severity=DiagnosticSeverity.HIGH,
            title="hl",
            summary="hl",
            evidence={},
            metric_value=None,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.LOW,
            source="x",
        )
        self.assertEqual(high_high.severity, high_low.severity)
        self.assertGreater(
            priority_score_for_diagnostic(high_high),
            priority_score_for_diagnostic(high_low),
        )

    def test_complete_data_headline_is_financial_not_partial(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        brief = build_adviser_brief(
            build_adviser_context(portfolio_view=view, diagnostics_view=_diagnostics(view))
        )
        self.assertTrue(brief.context.data_quality.valuation_complete)
        self.assertIn("dikkat", brief.headline.lower())

    def test_data_quality_firewall_matrix(self) -> None:
        complete_view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        complete = build_adviser_context(
            portfolio_view=complete_view,
            diagnostics_view=_diagnostics(complete_view),
        )
        self.assertTrue(complete.data_quality.valuation_complete)

        missing_price_view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=50.0,
            ),
            unpriced=1,
            unpriced_positions=[_position(symbol="MSFT", weight_pct=0.0, market_value=0.0)],
        )
        missing_price = build_adviser_context(
            portfolio_view=missing_price_view,
            diagnostics_view=_diagnostics(missing_price_view),
        )
        self.assertFalse(missing_price.data_quality.valuation_complete)
        self.assertEqual(
            build_adviser_brief(missing_price).headline,
            "Portföy analizi kısmi veriyle sınırlıdır.",
        )
        self.assertIsNone(missing_price.portfolio.relative_return_pct)

        mixed_view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
            mixed=True,
        )
        mixed = build_adviser_context(
            portfolio_view=mixed_view,
            diagnostics_view=_diagnostics(mixed_view),
        )
        self.assertTrue(mixed.data_quality.mixed_currency)

        foreign_view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
            foreign=1,
            foreign_positions=[_position(symbol="EUR", weight_pct=0.0, market_value=0.0)],
        )
        foreign = build_adviser_context(
            portfolio_view=foreign_view,
            diagnostics_view=_diagnostics(foreign_view),
        )
        self.assertTrue(foreign.data_quality.mixed_currency)
        self.assertEqual(foreign.portfolio.foreign_currency_position_count, 1)

        truncated = build_adviser_context(
            portfolio_view=complete_view,
            diagnostics_view=_diagnostics(complete_view, transaction_history_complete=False),
            transaction_history_complete=False,
        )
        self.assertFalse(truncated.data_quality.transaction_history_complete)

        perf = WealthPerformanceView(
            portfolio_id="pf-1",
            portfolio_name="Main",
            base_currency="USD",
            history_points=[],
            linked_performance=PortfolioLinkedPerformance(
                period_start_at="t1",
                period_end_at="t2",
                base_currency="USD",
                subperiod_count=1,
                linked_return_pct=None,
                performance_comparable=False,
                warnings=["x"],
                subperiods=[],
            ),
        )
        incomparable = build_adviser_context(
            portfolio_view=complete_view,
            diagnostics_view=_diagnostics(complete_view, performance_view=perf),
            performance_view=perf,
        )
        self.assertFalse(incomparable.data_quality.performance_comparable)
        self.assertIsNone(incomparable.portfolio.linked_return_pct)

    def test_nabi_invariance_includes_headline_and_financial_order(self) -> None:
        health = _full_health(
            largest_position_weight_pct=60.0,
            top3_concentration_pct=100.0,
            largest_asset_class_concentration_pct=100.0,
            cash_pct=0.0,
            invested_pct=100.0,
        )
        base_positions = [
            _position(symbol="AAPL", weight_pct=60.0, market_value=6000),
            _position(symbol="MSFT", weight_pct=40.0, market_value=4000),
        ]
        nabi = InvestmentIntelligenceView(
            symbol="X",
            market="NASDAQ",
            company_name="X",
            decision="BUY",
            nabi_score=95.0,
            participation_status=None,
            participation_score=None,
            research_status="ready",
            candidate_id="c1",
            has_candidate=True,
            has_participation_snapshot=False,
        )

        def _brief(positions):
            view = _view(positions=positions, health=health)
            return build_adviser_brief(
                build_adviser_context(
                    portfolio_view=view,
                    diagnostics_view=_diagnostics(view),
                )
            )

        no_nabi = _brief(base_positions)
        with_nabi = _brief(
            [
                _position(symbol="AAPL", weight_pct=60.0, market_value=6000, nabi=nabi),
                _position(symbol="MSFT", weight_pct=40.0, market_value=4000, nabi=nabi),
            ]
        )
        self.assertEqual(no_nabi.headline, with_nabi.headline)
        fin_no = [f.diagnostic_code for f in no_nabi.context.findings if f.category != "NABI_CONTEXT"]
        fin_with = [f.diagnostic_code for f in with_nabi.context.findings if f.category != "NABI_CONTEXT"]
        self.assertEqual(fin_no, fin_with)

    def test_brief_prohibited_claims_and_no_buy_sell_language(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        brief = build_adviser_brief(
            build_adviser_context(portfolio_view=view, diagnostics_view=_diagnostics(view))
        )
        required = [
            "Do not invent missing financial data.",
            "Do not override deterministic calculations.",
            "Do not claim certainty about future returns.",
            "Do not fabricate benchmark comparisons.",
            "Do not present NABI metadata as portfolio valuation evidence.",
            "Do not issue exact transaction instructions or specific security buy/sell recommendations.",
        ]
        for claim in required:
            self.assertIn(claim, brief.prohibited_claims)
        combined = " ".join(
            [brief.headline, brief.portfolio_summary, *brief.questions_for_user]
        ).lower()
        for phrase in ["buy", "sell", "sat", "al ", "öner"]:
            self.assertNotIn(phrase, combined)

    def test_partial_data_question_prioritized(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
                priced_position_coverage_pct=50.0,
            ),
            unpriced=1,
            unpriced_positions=[_position(symbol="MSFT", weight_pct=0.0, market_value=0.0)],
        )
        questions = build_questions(
            build_adviser_context(
                portfolio_view=view,
                diagnostics_view=_diagnostics(view),
            ).findings
        )
        self.assertTrue(questions)
        self.assertEqual(questions[0], "Eksik fiyatlanan varlıkları tamamlamak ister misiniz?")

    def test_no_nabi_only_questions(self) -> None:
        nabi = InvestmentIntelligenceView(
            symbol="X",
            market="NASDAQ",
            company_name="X",
            decision="BUY",
            nabi_score=95.0,
            participation_status=None,
            participation_score=None,
            research_status="ready",
            candidate_id="c1",
            has_candidate=True,
            has_participation_snapshot=False,
        )
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000, nabi=nabi)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        questions = build_questions(
            build_adviser_context(
                portfolio_view=view,
                diagnostics_view=_diagnostics(view),
            ).findings
        )
        self.assertFalse(any("nabi" in q.lower() for q in questions))

    def test_brief_serialization_json_safe_stable_without_provider_payloads(self) -> None:
        view = _view(
            positions=[_position(symbol="AAPL", weight_pct=100.0, market_value=1000)],
            health=_full_health(
                largest_position_weight_pct=100.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=100.0,
                cash_pct=0.0,
                invested_pct=100.0,
            ),
        )
        context = build_adviser_context(
            portfolio_view=view,
            diagnostics_view=_diagnostics(view),
        )
        brief = build_adviser_brief(context)
        first = json.dumps(brief.to_dict(), sort_keys=True)
        second = json.dumps(build_adviser_brief(context).to_dict(), sort_keys=True)
        self.assertEqual(first, second)
        lowered = first.lower()
        for banned in ["supabase", "streamlit", "provider_fetch", "session_state"]:
            self.assertNotIn(banned, lowered)

    def test_findings_ordering_stable_across_renders(self) -> None:
        view = _view(
            positions=[
                _position(symbol="CASH", weight_pct=85.0, market_value=8500, is_cash=True, asset_class="cash"),
                _position(symbol="AAPL", weight_pct=15.0, market_value=1500),
            ],
            health=_full_health(
                largest_position_weight_pct=85.0,
                top3_concentration_pct=100.0,
                largest_asset_class_concentration_pct=85.0,
                cash_pct=85.0,
                invested_pct=15.0,
            ),
        )
        kwargs = dict(
            portfolio_view=view,
            diagnostics_view=_diagnostics(view),
        )
        ids_a = [f.finding_id for f in build_adviser_context(**kwargs).findings]
        ids_b = [f.finding_id for f in build_adviser_context(**kwargs).findings]
        self.assertEqual(ids_a, ids_b)

    def test_adviser_ui_reuses_portfolio_view_no_duplicate_intelligence(self) -> None:
        source = Path("pages/10_Wealth.py").read_text(encoding="utf-8")
        adviser = source.split("with tab_adviser:")[1]
        self.assertIn("portfolio_view", adviser)
        self.assertNotIn("intelligence.build_view", adviser)
        self.assertIn("benchmark_view=None", adviser)
        self.assertNotIn("WealthBenchmarkService", adviser)

    def test_adviser_ui_no_free_form_fact_inputs(self) -> None:
        source = Path("pages/10_Wealth.py").read_text(encoding="utf-8")
        adviser = source.split("with tab_adviser:")[1].lower()
        self.assertIn('st.form("adviser_chat_form"', adviser)
        self.assertIn('st.form("adviser_profile_form"', adviser)
        self.assertNotIn("number_input", adviser)
        self.assertNotIn("service_role", source.lower())


if __name__ == "__main__":
    unittest.main()
