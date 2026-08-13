from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from services.portfolio_intelligence_contract import PortfolioIntelligenceView
from services.wealth_adviser_contract import (
    ADVISER_SCHEMA_VERSION,
    PROHIBITED_CLAIMS,
    AdviserBrief,
    AdviserContext,
    AdviserDataQuality,
    AdviserFinding,
    AdviserPortfolioFacts,
)
from services.wealth_diagnostics_contract import (
    DiagnosticCategory,
    DiagnosticConfidence,
    DiagnosticSeverity,
    PortfolioDiagnostic,
    PortfolioDiagnosticsView,
)
from services.wealth_timeline_contract import BenchmarkComparisonView, WealthPerformanceView

# priority_score is adviser presentation priority, NOT financial risk severity.
SEVERITY_BASE_SCORE = {
    DiagnosticSeverity.HIGH: 300,
    DiagnosticSeverity.WATCH: 200,
    DiagnosticSeverity.INFO: 100,
}
CONFIDENCE_ADJUSTMENT = {
    DiagnosticConfidence.HIGH: 30,
    DiagnosticConfidence.MEDIUM: 20,
    DiagnosticConfidence.LOW: 10,
}
CATEGORY_ADJUSTMENT = {
    DiagnosticCategory.DATA_QUALITY: 80,
    DiagnosticCategory.CONCENTRATION: 70,
    DiagnosticCategory.DIVERSIFICATION: 65,
    DiagnosticCategory.DRAWDOWN: 60,
    DiagnosticCategory.PERFORMANCE: 55,
    DiagnosticCategory.CASH: 50,
    DiagnosticCategory.BENCHMARK: 45,
    DiagnosticCategory.NABI_CONTEXT: 10,
}

STRUCTURAL_CATEGORIES = {
    DiagnosticCategory.CONCENTRATION,
    DiagnosticCategory.DIVERSIFICATION,
    DiagnosticCategory.CASH,
}
PERFORMANCE_CATEGORIES = {
    DiagnosticCategory.PERFORMANCE,
    DiagnosticCategory.DRAWDOWN,
    DiagnosticCategory.BENCHMARK,
}

MAX_USER_QUESTIONS = 3

QUESTION_BY_CATEGORY = {
    DiagnosticCategory.CONCENTRATION: "Bu yoğunlaşma bilinçli bir tercih mi?",
    DiagnosticCategory.DIVERSIFICATION: "Portföy çeşitliliği için hedeflediğiniz bir yapı var mı?",
    DiagnosticCategory.CASH: "Nakit için hedeflediğiniz bir alt veya üst sınır var mı?",
    DiagnosticCategory.PERFORMANCE: "Bu portföyü hangi yatırım ufkuyla değerlendiriyorsunuz?",
    DiagnosticCategory.DRAWDOWN: "Bu portföyü hangi yatırım ufkuyla değerlendiriyorsunuz?",
    DiagnosticCategory.DATA_QUALITY: "Eksik fiyatlanan varlıkları tamamlamak ister misiniz?",
}

QUESTION_BY_CODE = {
    "DATA_MIXED_CURRENCY": "Baz para birimi dışı pozisyonları takip etmek için FX desteği gerekir mi?",
    "DATA_TXN_HISTORY_TRUNCATED": "Tam performans yorumu için işlem geçmişini genişletmek ister misiniz?",
}


def priority_score_for_diagnostic(diagnostic: PortfolioDiagnostic) -> int:
    return (
        SEVERITY_BASE_SCORE[diagnostic.severity]
        + CONFIDENCE_ADJUSTMENT[diagnostic.confidence]
        + CATEGORY_ADJUSTMENT.get(diagnostic.category, 0)
    )


def _finding_sort_key(finding: AdviserFinding) -> Tuple[int, str, str, str]:
    return (-finding.priority_score, finding.category, finding.diagnostic_code, finding.finding_id)


def build_portfolio_facts(
    portfolio_view: PortfolioIntelligenceView,
    *,
    performance_view: Optional[WealthPerformanceView] = None,
    benchmark_view: Optional[BenchmarkComparisonView] = None,
    diagnostics_view: Optional[PortfolioDiagnosticsView] = None,
) -> AdviserPortfolioFacts:
    linked_return_pct: Optional[float] = None
    performance_comparable = False
    if performance_view and performance_view.linked_performance:
        performance_comparable = performance_view.linked_performance.performance_comparable
        if performance_comparable:
            linked_return_pct = performance_view.linked_performance.linked_return_pct

    if diagnostics_view is not None:
        performance_comparable = diagnostics_view.comparable_performance

    benchmark_available = False
    benchmark_return_pct: Optional[float] = None
    relative_return_pct: Optional[float] = None
    if benchmark_view and benchmark_view.performance_comparable:
        benchmark_available = True
        benchmark_return_pct = benchmark_view.benchmark_return_pct
        relative_return_pct = benchmark_view.relative_return_pct
    elif diagnostics_view is not None:
        benchmark_available = diagnostics_view.benchmark_available

    health = portfolio_view.health
    return AdviserPortfolioFacts(
        portfolio_id=portfolio_view.portfolio_id,
        portfolio_name=portfolio_view.portfolio_name,
        base_currency=portfolio_view.base_currency,
        priced_market_value=portfolio_view.priced_total_market_value,
        total_cost_basis=portfolio_view.priced_total_cost_basis,
        unrealized_pl=portfolio_view.priced_total_unrealized_pl,
        cash_pct=health.cash_pct,
        invested_pct=health.invested_pct,
        largest_position_pct=health.largest_position_weight_pct,
        top3_concentration_pct=health.top3_concentration_pct,
        largest_asset_class_pct=health.largest_asset_class_concentration_pct,
        priced_position_coverage_pct=health.priced_position_coverage_pct,
        unpriced_position_count=portfolio_view.unpriced_position_count,
        mixed_currency_warning=portfolio_view.mixed_currency_warning,
        foreign_currency_position_count=portfolio_view.foreign_currency_position_count,
        linked_return_pct=linked_return_pct,
        benchmark_return_pct=benchmark_return_pct,
        relative_return_pct=relative_return_pct,
        performance_comparable=performance_comparable,
        benchmark_available=benchmark_available,
    )


def build_data_quality(
    *,
    portfolio_view: PortfolioIntelligenceView,
    diagnostics_view: PortfolioDiagnosticsView,
    transaction_history_complete: bool,
) -> AdviserDataQuality:
    warnings: List[str] = []
    for diagnostic in diagnostics_view.diagnostics:
        if diagnostic.category == DiagnosticCategory.DATA_QUALITY:
            warnings.append(diagnostic.summary)

    if portfolio_view.mixed_currency_warning or portfolio_view.foreign_currency_position_count > 0:
        if not any("baz para birimi" in item.lower() for item in warnings):
            warnings.append(
                "Toplam değer ve ağırlıklar yalnızca fiyatlı baz para birimi alt kümesinde hesaplanır."
            )

    if portfolio_view.unpriced_position_count > 0:
        if not any("fiyat" in item.lower() for item in warnings):
            warnings.append(
                f"{portfolio_view.unpriced_position_count} pozisyonun güncel fiyatı yok."
            )

    if not diagnostics_view.comparable_performance:
        warnings.append("Performans yorumu karşılaştırılabilir değil veya yetersiz veri var.")

    if not diagnostics_view.benchmark_available:
        warnings.append("Benchmark karşılaştırması mevcut değil.")

    if not transaction_history_complete:
        warnings.append("İşlem geçmişi sınırlı olabilir; performans yorumu kısıtlıdır.")

    return AdviserDataQuality(
        valuation_complete=diagnostics_view.data_quality_ok,
        performance_comparable=diagnostics_view.comparable_performance,
        benchmark_available=diagnostics_view.benchmark_available,
        transaction_history_complete=transaction_history_complete,
        mixed_currency=(
            portfolio_view.mixed_currency_warning
            or portfolio_view.foreign_currency_position_count > 0
        ),
        unpriced_position_count=portfolio_view.unpriced_position_count,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _is_actionable(diagnostic: PortfolioDiagnostic) -> bool:
    if diagnostic.category == DiagnosticCategory.NABI_CONTEXT:
        return False
    return True


def _finding_limitations(
    diagnostic: PortfolioDiagnostic,
    data_quality: AdviserDataQuality,
) -> Tuple[str, ...]:
    limitations: List[str] = []

    if diagnostic.category in STRUCTURAL_CATEGORIES:
        if not data_quality.valuation_complete:
            limitations.append(
                "Bu bulgu yalnızca fiyatlı baz para birimi alt kümesine dayanır; "
                "tam portföy kapsamı sağlanmamış olabilir."
            )
        if data_quality.mixed_currency:
            limitations.append(
                "Karışık para birimi nedeniyle toplam portföy ağırlıkları kısmi olabilir."
            )

    if diagnostic.category in PERFORMANCE_CATEGORIES:
        if not data_quality.performance_comparable:
            limitations.append("Performans verisi karşılaştırılabilir değil.")
        if not data_quality.transaction_history_complete:
            limitations.append("İşlem geçmişi sınırlı olabilir.")

    if diagnostic.category == DiagnosticCategory.BENCHMARK and not data_quality.benchmark_available:
        limitations.append("Benchmark karşılaştırması mevcut değil.")

    if diagnostic.confidence == DiagnosticConfidence.LOW:
        limitations.append("Tanı güveni düşük; yorum dikkatle yapılmalıdır.")

    return tuple(dict.fromkeys(limitations))


def diagnostic_to_finding(
    diagnostic: PortfolioDiagnostic,
    *,
    data_quality: AdviserDataQuality,
) -> AdviserFinding:
    finding_id = f"{diagnostic.category.value}:{diagnostic.code}"
    return AdviserFinding(
        finding_id=finding_id,
        diagnostic_code=diagnostic.code,
        category=diagnostic.category.value,
        severity=diagnostic.severity.value,
        confidence=diagnostic.confidence.value,
        title=diagnostic.title,
        statement=diagnostic.summary,
        evidence=dict(diagnostic.evidence),
        affected_symbols=tuple(diagnostic.affected_symbols),
        source=diagnostic.source,
        priority_score=priority_score_for_diagnostic(diagnostic),
        actionable=_is_actionable(diagnostic),
        limitations=_finding_limitations(diagnostic, data_quality),
    )


def build_findings(
    diagnostics_view: PortfolioDiagnosticsView,
    *,
    data_quality: AdviserDataQuality,
) -> Tuple[AdviserFinding, ...]:
    findings = [
        diagnostic_to_finding(diagnostic, data_quality=data_quality)
        for diagnostic in diagnostics_view.diagnostics
    ]
    return tuple(sorted(findings, key=_finding_sort_key))


def build_questions(findings: Sequence[AdviserFinding]) -> Tuple[str, ...]:
    questions: List[str] = []
    for finding in sorted(findings, key=_finding_sort_key):
        if not finding.actionable:
            continue
        question = QUESTION_BY_CODE.get(finding.diagnostic_code)
        if question is None:
            try:
                category = DiagnosticCategory(finding.category)
            except ValueError:
                continue
            question = QUESTION_BY_CATEGORY.get(category)
        if question and question not in questions:
            questions.append(question)
        if len(questions) >= MAX_USER_QUESTIONS:
            break
    return tuple(questions)


def _headline_for_context(
    findings: Sequence[AdviserFinding],
    data_quality: AdviserDataQuality,
) -> str:
    if not data_quality.valuation_complete:
        return "Portföy analizi kısmi veriyle sınırlıdır."
    actionable = [item for item in findings if item.actionable]
    if not actionable:
        return "Belirgin bir yapısal bulgu yok; veri kalitesi notlarına bakın."
    top = sorted(actionable, key=_finding_sort_key)[0]
    if top.severity == DiagnosticSeverity.HIGH.value:
        return f"Portföyde dikkat gerektiren bir bulgu var: {top.title.lower()}."
    if top.severity == DiagnosticSeverity.WATCH.value:
        return f"Portföyde izlenmesi gereken bir bulgu var: {top.title.lower()}."
    return "Portföy yapısı hakkında bilgilendirici bulgular mevcut."


def _portfolio_summary(facts: AdviserPortfolioFacts) -> str:
    return (
        f"Fiyatlı {facts.base_currency} portföy değeri "
        f"{facts.priced_market_value:,.2f} {facts.base_currency}; "
        f"en büyük pozisyon %{facts.largest_position_pct:.1f}, "
        f"nakit %{facts.cash_pct:.1f}, yatırım %{facts.invested_pct:.1f}."
    )


def build_adviser_brief(context: AdviserContext) -> AdviserBrief:
    findings = context.findings
    actionable = [item for item in findings if item.actionable]
    top_pool = actionable if actionable else list(findings)
    ordered = sorted(top_pool, key=_finding_sort_key)
    top_findings = tuple(ordered[:3])
    top_ids = {item.finding_id for item in top_findings}
    supporting_findings = tuple(
        item for item in findings if item.finding_id not in top_ids
    )

    data_quality_notes = context.data_quality.warnings
    if not context.data_quality.valuation_complete:
        data_quality_notes = tuple(
            dict.fromkeys(
                (
                    "Tam portföy değerlemesi mevcut değil; yapısal yorumlar kısmi veriye dayanır.",
                    *data_quality_notes,
                )
            )
        )

    return AdviserBrief(
        headline=_headline_for_context(findings, context.data_quality),
        portfolio_summary=_portfolio_summary(context.portfolio),
        top_findings=top_findings,
        supporting_findings=supporting_findings,
        data_quality_notes=data_quality_notes,
        questions_for_user=build_questions(findings),
        prohibited_claims=PROHIBITED_CLAIMS,
        context=context,
    )


def build_adviser_context(
    *,
    portfolio_view: PortfolioIntelligenceView,
    diagnostics_view: PortfolioDiagnosticsView,
    performance_view: Optional[WealthPerformanceView] = None,
    benchmark_view: Optional[BenchmarkComparisonView] = None,
    transaction_history_complete: bool = True,
    generated_from_snapshot_count: int = 0,
) -> AdviserContext:
    data_quality = build_data_quality(
        portfolio_view=portfolio_view,
        diagnostics_view=diagnostics_view,
        transaction_history_complete=transaction_history_complete,
    )
    portfolio = build_portfolio_facts(
        portfolio_view,
        performance_view=performance_view,
        benchmark_view=benchmark_view,
        diagnostics_view=diagnostics_view,
    )
    findings = build_findings(diagnostics_view, data_quality=data_quality)
    return AdviserContext(
        portfolio=portfolio,
        findings=findings,
        data_quality=data_quality,
        generated_from_snapshot_count=generated_from_snapshot_count,
        deterministic_only=True,
        schema_version=ADVISER_SCHEMA_VERSION,
    )
