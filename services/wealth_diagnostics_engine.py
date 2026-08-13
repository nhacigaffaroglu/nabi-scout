from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.portfolio_intelligence_contract import PortfolioIntelligenceView, PositionValuationRow
from services.wealth_diagnostics_contract import (
    DiagnosticCategory,
    DiagnosticConfidence,
    DiagnosticSeverity,
    PortfolioDiagnostic,
    PortfolioDiagnosticsView,
)
from services.wealth_timeline_contract import (
    BenchmarkComparisonView,
    PortfolioHistoryPoint,
    WealthPerformanceView,
)

# --- Concentration thresholds (priced base-currency weights) ---
SINGLE_POSITION_WATCH_PCT = 25.0
SINGLE_POSITION_HIGH_PCT = 40.0
TOP3_WATCH_PCT = 65.0
TOP3_HIGH_PCT = 80.0
ASSET_CLASS_WATCH_PCT = 65.0
ASSET_CLASS_HIGH_PCT = 80.0

# --- Diversification thresholds (effective position count) ---
EFFECTIVE_COUNT_WATCH = 4.0
EFFECTIVE_COUNT_HIGH = 2.0

# --- Cash exposure thresholds ---
CASH_WATCH_PCT = 50.0
CASH_HIGH_PCT = 80.0

# --- Benchmark relative thresholds (percentage points) ---
BENCHMARK_LAG_WATCH_PP = -10.0

# --- Unrealized loss breadth (invested positions) ---
LOSS_BREADTH_WATCH_PCT = 50.0

_SEVERITY_ORDER = {
    DiagnosticSeverity.HIGH: 0,
    DiagnosticSeverity.WATCH: 1,
    DiagnosticSeverity.INFO: 2,
}


def _structural_confidence(view: PortfolioIntelligenceView) -> DiagnosticConfidence:
    if view.mixed_currency_warning or view.foreign_currency_position_count > 0:
        return DiagnosticConfidence.LOW
    if (
        view.health.priced_position_coverage_pct >= 100.0
        and view.unpriced_position_count == 0
    ):
        return DiagnosticConfidence.HIGH
    if view.health.priced_position_coverage_pct >= 80.0:
        return DiagnosticConfidence.MEDIUM
    return DiagnosticConfidence.LOW


def _weights_trustworthy(view: PortfolioIntelligenceView) -> bool:
    return (
        view.health.priced_position_coverage_pct >= 100.0
        and view.unpriced_position_count == 0
        and not view.mixed_currency_warning
        and view.foreign_currency_position_count == 0
        and view.priced_total_market_value > 0
    )


def _priced_base_positions(view: PortfolioIntelligenceView) -> List[PositionValuationRow]:
    return [
        row
        for row in view.priced_positions
        if row.included_in_base_totals and row.weight_pct is not None
    ]


def _invested_priced_positions(view: PortfolioIntelligenceView) -> List[PositionValuationRow]:
    return [
        row
        for row in _priced_base_positions(view)
        if not row.is_cash and row.market_value is not None
    ]


def effective_position_count(view: PortfolioIntelligenceView) -> Optional[float]:
    if not _weights_trustworthy(view):
        return None
    weights = [row.weight_pct / 100.0 for row in _priced_base_positions(view)]
    if not weights:
        return None
    herfindahl = sum(weight * weight for weight in weights)
    if herfindahl <= 0:
        return None
    return 1.0 / herfindahl


def _severity_for_threshold(
    value: float,
    *,
    watch: float,
    high: float,
    higher_is_worse: bool = True,
) -> Optional[DiagnosticSeverity]:
    if higher_is_worse:
        if value >= high:
            return DiagnosticSeverity.HIGH
        if value >= watch:
            return DiagnosticSeverity.WATCH
        return None
    if value <= high:
        return DiagnosticSeverity.HIGH
    if value <= watch:
        return DiagnosticSeverity.WATCH
    return None


def _severity_for_effective_count(value: float) -> Optional[DiagnosticSeverity]:
    """Strict boundaries: HIGH if value < 2; WATCH if 2 <= value < 4."""
    if value < EFFECTIVE_COUNT_HIGH:
        return DiagnosticSeverity.HIGH
    if value < EFFECTIVE_COUNT_WATCH:
        return DiagnosticSeverity.WATCH
    return None


def _largest_position_row(view: PortfolioIntelligenceView) -> Optional[PositionValuationRow]:
    candidates = _priced_base_positions(view)
    if not candidates:
        return None
    return max(candidates, key=lambda row: row.weight_pct or 0.0)


def build_data_quality_diagnostics(
    *,
    portfolio_view: PortfolioIntelligenceView,
    performance_view: Optional[WealthPerformanceView],
    benchmark_view: Optional[BenchmarkComparisonView],
    transaction_history_complete: bool,
) -> List[PortfolioDiagnostic]:
    diagnostics: List[PortfolioDiagnostic] = []
    view = portfolio_view

    if view.unpriced_position_count > 0:
        diagnostics.append(
            PortfolioDiagnostic(
                code="DATA_PRICE_COVERAGE",
                category=DiagnosticCategory.DATA_QUALITY,
                severity=DiagnosticSeverity.WATCH,
                title="Eksik fiyat kapsamı",
                summary=(
                    f"{view.unpriced_position_count} / {view.total_position_count} "
                    "pozisyonun güncel fiyatı yok; yapısal metrikler yalnızca fiyatlı "
                    "baz para birimi alt kümesini kapsar."
                ),
                evidence={
                    "unpriced_position_count": view.unpriced_position_count,
                    "total_position_count": view.total_position_count,
                    "priced_position_coverage_pct": view.health.priced_position_coverage_pct,
                },
                metric_value=float(view.unpriced_position_count),
                threshold=None,
                affected_symbols=[
                    row.symbol for row in view.unpriced_positions if row.symbol
                ],
                confidence=DiagnosticConfidence.HIGH,
                source="portfolio_intelligence",
            )
        )

    if view.mixed_currency_warning or view.foreign_currency_position_count > 0:
        diagnostics.append(
            PortfolioDiagnostic(
                code="DATA_MIXED_CURRENCY",
                category=DiagnosticCategory.DATA_QUALITY,
                severity=DiagnosticSeverity.WATCH,
                title="Karışık para birimi",
                summary=(
                    "Portföyde baz para birimi dışındaki pozisyonlar var; "
                    "toplam değer ve ağırlıklar yalnızca fiyatlı baz para birimi "
                    "alt kümesinde hesaplanır."
                ),
                evidence={
                    "mixed_currency_warning": view.mixed_currency_warning,
                    "foreign_currency_position_count": view.foreign_currency_position_count,
                    "base_currency": view.base_currency,
                },
                metric_value=float(view.foreign_currency_position_count),
                threshold=None,
                affected_symbols=[
                    row.symbol for row in view.foreign_currency_positions if row.symbol
                ],
                confidence=DiagnosticConfidence.HIGH,
                source="portfolio_intelligence",
            )
        )

    if not transaction_history_complete:
        diagnostics.append(
            PortfolioDiagnostic(
                code="DATA_TXN_HISTORY_TRUNCATED",
                category=DiagnosticCategory.DATA_QUALITY,
                severity=DiagnosticSeverity.WATCH,
                title="İşlem geçmişi sınırlı",
                summary=(
                    "İşlem geçmişi üst sınıra ulaşmış olabilir; performans ve dış akış "
                    "tanıları tam güvenilir olmayabilir."
                ),
                evidence={"transaction_history_complete": False},
                metric_value=None,
                threshold=None,
                affected_symbols=[],
                confidence=DiagnosticConfidence.MEDIUM,
                source="wealth_timeline",
            )
        )

    snapshot_count = len(performance_view.history_points) if performance_view else 0
    if snapshot_count < 2:
        diagnostics.append(
            PortfolioDiagnostic(
                code="DATA_INSUFFICIENT_SNAPSHOTS",
                category=DiagnosticCategory.DATA_QUALITY,
                severity=DiagnosticSeverity.INFO,
                title="Yetersiz görüntü geçmişi",
                summary=(
                    "Kayıtlı portföy görüntüsü sayısı dönemsel performans ve "
                    "drawdown tanıları için yetersiz (en az 2 gerekir)."
                ),
                evidence={"snapshot_count": snapshot_count},
                metric_value=float(snapshot_count),
                threshold=2.0,
                affected_symbols=[],
                confidence=DiagnosticConfidence.HIGH,
                source="wealth_timeline",
            )
        )

    if benchmark_view is not None and not benchmark_view.performance_comparable:
        diagnostics.append(
            PortfolioDiagnostic(
                code="DATA_BENCHMARK_UNAVAILABLE",
                category=DiagnosticCategory.DATA_QUALITY,
                severity=DiagnosticSeverity.INFO,
                title="Benchmark karşılaştırması kullanılamıyor",
                summary=(
                    "SPY tarihsel karşılaştırması mevcut veriyle tam üretilemedi."
                ),
                evidence={"warnings": list(benchmark_view.warnings)},
                metric_value=None,
                threshold=None,
                affected_symbols=[],
                confidence=DiagnosticConfidence.HIGH,
                source="wealth_benchmark",
            )
        )

    if view.health.priced_position_coverage_pct < 100.0:
        diagnostics.append(
            PortfolioDiagnostic(
                code="DATA_PARTIAL_VALUATION",
                category=DiagnosticCategory.DATA_QUALITY,
                severity=DiagnosticSeverity.INFO,
                title="Kısmi değerleme",
                summary=(
                    f"Fiyatlı pozisyon kapsamı %{view.health.priced_position_coverage_pct:.0f}; "
                    "yapısal tanılar sınırlı güvenle yorumlanmalıdır."
                ),
                evidence={
                    "priced_position_coverage_pct": view.health.priced_position_coverage_pct,
                },
                metric_value=view.health.priced_position_coverage_pct,
                threshold=100.0,
                affected_symbols=[],
                confidence=DiagnosticConfidence.HIGH,
                source="portfolio_intelligence",
            )
        )

    return diagnostics


def build_concentration_diagnostics(
    portfolio_view: PortfolioIntelligenceView,
) -> List[PortfolioDiagnostic]:
    diagnostics: List[PortfolioDiagnostic] = []
    if not _weights_trustworthy(portfolio_view):
        return diagnostics

    confidence = _structural_confidence(portfolio_view)
    health = portfolio_view.health
    largest = _largest_position_row(portfolio_view)
    largest_pct = health.largest_position_weight_pct
    severity = _severity_for_threshold(
        largest_pct,
        watch=SINGLE_POSITION_WATCH_PCT,
        high=SINGLE_POSITION_HIGH_PCT,
    )
    if severity is not None and largest is not None:
        diagnostics.append(
            PortfolioDiagnostic(
                code=(
                    "CONCENTRATION_SINGLE_HIGH"
                    if severity == DiagnosticSeverity.HIGH
                    else "CONCENTRATION_SINGLE_WATCH"
                ),
                category=DiagnosticCategory.CONCENTRATION,
                severity=severity,
                title="Tek pozisyon yoğunlaşması",
                summary=(
                    f"En büyük fiyatlı pozisyon, fiyatlı baz para birimi portföy "
                    f"değerinin %{largest_pct:.1f} kadarını temsil eder "
                    f"({largest.symbol})."
                ),
                evidence={
                    "largest_position_pct": largest_pct,
                    "symbol": largest.symbol,
                },
                metric_value=largest_pct,
                threshold=(
                    SINGLE_POSITION_HIGH_PCT
                    if severity == DiagnosticSeverity.HIGH
                    else SINGLE_POSITION_WATCH_PCT
                ),
                affected_symbols=[largest.symbol],
                confidence=confidence,
                source="portfolio_intelligence",
            )
        )

    top3_pct = health.top3_concentration_pct
    severity = _severity_for_threshold(
        top3_pct,
        watch=TOP3_WATCH_PCT,
        high=TOP3_HIGH_PCT,
    )
    if severity is not None:
        top_symbols = [
            row.symbol
            for row in sorted(
                _priced_base_positions(portfolio_view),
                key=lambda row: row.weight_pct or 0.0,
                reverse=True,
            )[:3]
        ]
        diagnostics.append(
            PortfolioDiagnostic(
                code=(
                    "CONCENTRATION_TOP3_HIGH"
                    if severity == DiagnosticSeverity.HIGH
                    else "CONCENTRATION_TOP3_WATCH"
                ),
                category=DiagnosticCategory.CONCENTRATION,
                severity=severity,
                title="İlk 3 pozisyon yoğunlaşması",
                summary=(
                    f"En büyük üç fiyatlı pozisyon toplam ağırlığı %{top3_pct:.1f}."
                ),
                evidence={
                    "top3_concentration_pct": top3_pct,
                    "symbols": top_symbols,
                },
                metric_value=top3_pct,
                threshold=(
                    TOP3_HIGH_PCT
                    if severity == DiagnosticSeverity.HIGH
                    else TOP3_WATCH_PCT
                ),
                affected_symbols=top_symbols,
                confidence=confidence,
                source="portfolio_intelligence",
            )
        )

    asset_class_pct = health.largest_asset_class_concentration_pct
    severity = _severity_for_threshold(
        asset_class_pct,
        watch=ASSET_CLASS_WATCH_PCT,
        high=ASSET_CLASS_HIGH_PCT,
    )
    if severity is not None:
        largest_slice = max(
            portfolio_view.asset_class_allocation,
            key=lambda row: row.weight_pct,
            default=None,
        )
        asset_label = largest_slice.label if largest_slice else "unknown"
        diagnostics.append(
            PortfolioDiagnostic(
                code=(
                    "CONCENTRATION_ASSET_CLASS_HIGH"
                    if severity == DiagnosticSeverity.HIGH
                    else "CONCENTRATION_ASSET_CLASS_WATCH"
                ),
                category=DiagnosticCategory.CONCENTRATION,
                severity=severity,
                title="Varlık sınıfı yoğunlaşması",
                summary=(
                    f"En büyük varlık sınıfı ({asset_label}) fiyatlı portföy "
                    f"ağırlığının %{asset_class_pct:.1f} kadarını oluşturur."
                ),
                evidence={
                    "largest_asset_class_concentration_pct": asset_class_pct,
                    "asset_class": asset_label,
                },
                metric_value=asset_class_pct,
                threshold=(
                    ASSET_CLASS_HIGH_PCT
                    if severity == DiagnosticSeverity.HIGH
                    else ASSET_CLASS_WATCH_PCT
                ),
                affected_symbols=[],
                confidence=confidence,
                source="portfolio_intelligence",
            )
        )

    return diagnostics


def build_diversification_diagnostics(
    portfolio_view: PortfolioIntelligenceView,
) -> List[PortfolioDiagnostic]:
    effective = effective_position_count(portfolio_view)
    if effective is None:
        return []

    confidence = _structural_confidence(portfolio_view)
    severity = _severity_for_effective_count(effective)
    if severity is None:
        return []

    return [
        PortfolioDiagnostic(
            code=(
                "DIVERSIFICATION_EFFECTIVE_LOW"
                if severity == DiagnosticSeverity.HIGH
                else "DIVERSIFICATION_EFFECTIVE_MODERATE"
            ),
            category=DiagnosticCategory.DIVERSIFICATION,
            severity=severity,
            title="Etkin pozisyon sayısı",
            summary=(
                f"Etkin pozisyon sayısı (1/Σw²) {effective:.2f}; "
                f"fiyatlı baz para birimi ağırlıklarına göre hesaplanmıştır."
            ),
            evidence={
                "effective_position_count": effective,
                "priced_position_count": portfolio_view.priced_position_count,
                "distinct_asset_class_count": len(portfolio_view.asset_class_allocation),
            },
            metric_value=effective,
            threshold=(
                EFFECTIVE_COUNT_HIGH
                if severity == DiagnosticSeverity.HIGH
                else EFFECTIVE_COUNT_WATCH
            ),
            affected_symbols=[],
            confidence=confidence,
            source="portfolio_intelligence",
        )
    ]


def build_cash_diagnostics(
    portfolio_view: PortfolioIntelligenceView,
) -> List[PortfolioDiagnostic]:
    if not _weights_trustworthy(portfolio_view):
        return []

    confidence = _structural_confidence(portfolio_view)
    cash_pct = portfolio_view.health.cash_pct
    severity = _severity_for_threshold(
        cash_pct,
        watch=CASH_WATCH_PCT,
        high=CASH_HIGH_PCT,
    )
    if severity is None:
        return []

    return [
        PortfolioDiagnostic(
            code=(
                "CASH_WEIGHT_HIGH"
                if severity == DiagnosticSeverity.HIGH
                else "CASH_WEIGHT_ELEVATED"
            ),
            category=DiagnosticCategory.CASH,
            severity=severity,
            title="Nakit ağırlığı",
            summary=(
                f"Nakit, fiyatlı baz para birimi portföy değerinin "
                f"%{cash_pct:.1f} kadarını temsil eder."
            ),
            evidence={"cash_pct": cash_pct},
            metric_value=cash_pct,
            threshold=CASH_HIGH_PCT if severity == DiagnosticSeverity.HIGH else CASH_WATCH_PCT,
            affected_symbols=[],
            confidence=confidence,
            source="portfolio_intelligence",
        )
    ]


def build_pl_structure_diagnostics(
    portfolio_view: PortfolioIntelligenceView,
) -> List[PortfolioDiagnostic]:
    invested = _invested_priced_positions(portfolio_view)
    if not invested:
        return []

    confidence = _structural_confidence(portfolio_view)
    profitable = 0
    losing = 0
    flat = 0
    largest_gain: Optional[Tuple[str, float]] = None
    largest_loss: Optional[Tuple[str, float]] = None

    total_invested_mv = 0.0
    loss_market_value = 0.0

    for row in invested:
        pl = row.unrealized_pl
        if pl is None:
            continue
        if row.market_value is not None:
            total_invested_mv += row.market_value
        if pl > 1e-9:
            profitable += 1
            if largest_gain is None or pl > largest_gain[1]:
                largest_gain = (row.symbol, pl)
        elif pl < -1e-9:
            losing += 1
            if row.market_value is not None:
                loss_market_value += row.market_value
            if largest_loss is None or pl < largest_loss[1]:
                largest_loss = (row.symbol, pl)
        else:
            flat += 1

    total = profitable + losing + flat
    if total == 0:
        return []

    loss_position_pct = (losing / total) * 100.0
    loss_market_value_pct = (
        (loss_market_value / total_invested_mv) * 100.0 if total_invested_mv > 0 else None
    )
    diagnostics: List[PortfolioDiagnostic] = [
        PortfolioDiagnostic(
            code="PERFORMANCE_PL_STRUCTURE",
            category=DiagnosticCategory.PERFORMANCE,
            severity=DiagnosticSeverity.INFO,
            title="Gerçekleşmemiş K/Z yapısı",
            summary=(
                f"{profitable} kârlı, {losing} zararda, {flat} nötr; "
                f"toplam {total} fiyatlı yatırım pozisyonu."
            ),
            evidence={
                "profitable_position_count": profitable,
                "losing_position_count": losing,
                "flat_position_count": flat,
                "invested_position_count": total,
            },
            metric_value=float(total),
            threshold=None,
            affected_symbols=[],
            confidence=confidence,
            source="portfolio_intelligence",
        )
    ]

    if losing > 0:
        severity = (
            DiagnosticSeverity.WATCH
            if loss_position_pct >= LOSS_BREADTH_WATCH_PCT
            else DiagnosticSeverity.INFO
        )
        diagnostics.append(
            PortfolioDiagnostic(
                code="UNREALIZED_LOSS_BREADTH",
                category=DiagnosticCategory.PERFORMANCE,
                severity=severity,
                title="Zararda pozisyon oranı",
                summary=(
                    f"{losing} / {total} fiyatlı yatırım pozisyonunda "
                    "gerçekleşmemiş zarar var."
                ),
                evidence={
                    "losing_position_count": losing,
                    "invested_position_count": total,
                    "loss_position_pct": loss_position_pct,
                    "loss_market_value_pct": loss_market_value_pct,
                    "loss_market_value": loss_market_value,
                    "total_invested_market_value": total_invested_mv,
                    "largest_gain_loss_unit": portfolio_view.base_currency,
                },
                metric_value=loss_position_pct,
                threshold=LOSS_BREADTH_WATCH_PCT,
                affected_symbols=[
                    row.symbol
                    for row in invested
                    if row.unrealized_pl is not None and row.unrealized_pl < -1e-9
                ],
                confidence=confidence,
                source="portfolio_intelligence",
            )
        )

    if largest_gain is not None:
        diagnostics.append(
            PortfolioDiagnostic(
                code="PERFORMANCE_LARGEST_GAIN",
                category=DiagnosticCategory.PERFORMANCE,
                severity=DiagnosticSeverity.INFO,
                title="En büyük gerçekleşmemiş kazanç",
                summary=(
                    f"{largest_gain[0]} pozisyonunda "
                    f"{largest_gain[1]:,.2f} {portfolio_view.base_currency} "
                    "gerçekleşmemiş kazanç."
                ),
                evidence={
                    "symbol": largest_gain[0],
                    "unrealized_pl": largest_gain[1],
                    "unit": portfolio_view.base_currency,
                },
                metric_value=largest_gain[1],
                threshold=None,
                affected_symbols=[largest_gain[0]],
                confidence=confidence,
                source="portfolio_intelligence",
            )
        )

    if largest_loss is not None:
        diagnostics.append(
            PortfolioDiagnostic(
                code="PERFORMANCE_LARGEST_LOSS",
                category=DiagnosticCategory.PERFORMANCE,
                severity=DiagnosticSeverity.INFO,
                title="En büyük gerçekleşmemiş zarar",
                summary=(
                    f"{largest_loss[0]} pozisyonunda "
                    f"{largest_loss[1]:,.2f} {portfolio_view.base_currency} "
                    "gerçekleşmemiş zarar."
                ),
                evidence={
                    "symbol": largest_loss[0],
                    "unrealized_pl": largest_loss[1],
                    "unit": portfolio_view.base_currency,
                },
                metric_value=largest_loss[1],
                threshold=None,
                affected_symbols=[largest_loss[0]],
                confidence=confidence,
                source="portfolio_intelligence",
            )
        )

    return diagnostics


def _drawdown_from_series(
    points: Sequence[Tuple[str, float]],
) -> Dict[str, Any]:
    running_peak_value = points[0][1]
    running_peak_at = points[0][0]
    max_drawdown_pct = 0.0
    max_drawdown_peak_at = points[0][0]
    max_drawdown_peak_value = points[0][1]
    trough_value = points[0][1]
    trough_at = points[0][0]

    for label, value in points:
        if value > running_peak_value:
            running_peak_value = value
            running_peak_at = label
        drawdown_pct = (
            ((value / running_peak_value) - 1.0) * 100.0 if running_peak_value > 0 else 0.0
        )
        if drawdown_pct < max_drawdown_pct:
            max_drawdown_pct = drawdown_pct
            max_drawdown_peak_at = running_peak_at
            max_drawdown_peak_value = running_peak_value
            trough_value = value
            trough_at = label

    current_drawdown_pct = (
        ((points[-1][1] / running_peak_value) - 1.0) * 100.0
        if running_peak_value > 0
        else 0.0
    )
    return {
        "current_drawdown_pct": current_drawdown_pct,
        "max_observed_drawdown_pct": max_drawdown_pct,
        "peak_at": max_drawdown_peak_at,
        "trough_at": trough_at,
        "peak_value": max_drawdown_peak_value,
        "trough_value": trough_value,
        "current_value": points[-1][1],
        "current_peak_at": running_peak_at,
        "current_peak_value": running_peak_value,
    }


def build_drawdown_diagnostics(
    *,
    history_points: Sequence[PortfolioHistoryPoint],
    performance_index_points: Optional[Sequence[Tuple[str, float]]],
    comparable_performance: bool,
) -> List[PortfolioDiagnostic]:
    diagnostics: List[PortfolioDiagnostic] = []

    if len(history_points) >= 2:
        raw_points = [
            (point.captured_at, point.priced_market_value) for point in history_points
        ]
        raw = _drawdown_from_series(raw_points)
        diagnostics.append(
            PortfolioDiagnostic(
                code="DRAWDOWN_RAW_SNAPSHOT",
                category=DiagnosticCategory.DRAWDOWN,
                severity=DiagnosticSeverity.INFO,
                title="Ham kayıtlı değer drawdown",
                summary=(
                    "Kayıtlı görüntü değerlerine göre ham drawdown; dış akışlar "
                    f"değeri etkileyebilir. Güncel: {raw['current_drawdown_pct']:.2f}%, "
                    f"maksimum gözlemlenen: {raw['max_observed_drawdown_pct']:.2f}%."
                ),
                evidence={
                    **raw,
                    "drawdown_kind": "raw_recorded_value",
                },
                metric_value=raw["max_observed_drawdown_pct"],
                threshold=None,
                affected_symbols=[],
                confidence=DiagnosticConfidence.MEDIUM,
                source="wealth_timeline",
            )
        )

    if (
        comparable_performance
        and performance_index_points
        and len(performance_index_points) >= 2
    ):
        perf = _drawdown_from_series(list(performance_index_points))
        severity = DiagnosticSeverity.INFO
        if perf["max_observed_drawdown_pct"] <= -20.0:
            severity = DiagnosticSeverity.WATCH
        if perf["max_observed_drawdown_pct"] <= -35.0:
            severity = DiagnosticSeverity.HIGH
        diagnostics.append(
            PortfolioDiagnostic(
                code="DRAWDOWN_PERFORMANCE",
                category=DiagnosticCategory.DRAWDOWN,
                severity=severity,
                title="Performans endeksi drawdown",
                summary=(
                    "Zincirlenmiş performans endeksine göre drawdown "
                    f"(başlangıç=100). Güncel: {perf['current_drawdown_pct']:.2f}%, "
                    f"maksimum gözlemlenen: {perf['max_observed_drawdown_pct']:.2f}%."
                ),
                evidence={
                    **perf,
                    "drawdown_kind": "performance_index",
                },
                metric_value=perf["max_observed_drawdown_pct"],
                threshold=None,
                affected_symbols=[],
                confidence=DiagnosticConfidence.HIGH,
                source="wealth_performance",
            )
        )

    return diagnostics


def build_benchmark_diagnostics(
    benchmark_view: Optional[BenchmarkComparisonView],
) -> List[PortfolioDiagnostic]:
    if benchmark_view is None or not benchmark_view.performance_comparable:
        return []

    relative = benchmark_view.relative_return_pct
    if relative is None:
        return []

    diagnostics: List[PortfolioDiagnostic] = [
        PortfolioDiagnostic(
            code="BENCHMARK_COMPARISON",
            category=DiagnosticCategory.BENCHMARK,
            severity=DiagnosticSeverity.INFO,
            title="Tarihsel benchmark karşılaştırması",
            summary=(
                f"Karşılaştırılabilir kayıtlı dönemde portföy getirisi "
                f"{benchmark_view.portfolio_return_pct:.2f}%, "
                f"{benchmark_view.benchmark_symbol} getirisi "
                f"{benchmark_view.benchmark_return_pct:.2f}%, "
                f"göreli fark {relative:+.2f} puan."
            ),
            evidence={
                "portfolio_return_pct": benchmark_view.portfolio_return_pct,
                "benchmark_return_pct": benchmark_view.benchmark_return_pct,
                "relative_return_pct": relative,
                "benchmark_symbol": benchmark_view.benchmark_symbol,
            },
            metric_value=relative,
            threshold=None,
            affected_symbols=[],
            confidence=DiagnosticConfidence.HIGH,
            source="wealth_benchmark",
        )
    ]

    if relative <= BENCHMARK_LAG_WATCH_PP:
        diagnostics.append(
            PortfolioDiagnostic(
                code="BENCHMARK_LAG",
                category=DiagnosticCategory.BENCHMARK,
                severity=DiagnosticSeverity.WATCH,
                title="Benchmark gerisinde kalma",
                summary=(
                    f"Karşılaştırılabilir kayıtlı dönemde portföy performansı "
                    f"{benchmark_view.benchmark_symbol} gerisinde "
                    f"{abs(relative):.1f} puan."
                ),
                evidence={
                    "relative_return_pct": relative,
                    "benchmark_symbol": benchmark_view.benchmark_symbol,
                },
                metric_value=relative,
                threshold=BENCHMARK_LAG_WATCH_PP,
                affected_symbols=[],
                confidence=DiagnosticConfidence.HIGH,
                source="wealth_benchmark",
            )
        )

    return diagnostics


def build_nabi_context_diagnostics(
    portfolio_view: PortfolioIntelligenceView,
) -> List[PortfolioDiagnostic]:
    symbols = [
        row.symbol
        for row in portfolio_view.priced_positions
        if row.symbol and not row.is_cash
    ]
    if not symbols:
        return []

    covered = 0
    decisions: Dict[str, int] = {}
    missing: List[str] = []
    for row in portfolio_view.priced_positions:
        if row.is_cash or not row.symbol:
            continue
        nabi = row.nabi
        if nabi is None or not (nabi.has_candidate or nabi.has_participation_snapshot):
            missing.append(row.symbol)
            continue
        covered += 1
        decision = nabi.decision or "unknown"
        decisions[decision] = decisions.get(decision, 0) + 1

    total = len(symbols)
    diagnostics: List[PortfolioDiagnostic] = [
        PortfolioDiagnostic(
            code="NABI_COVERAGE",
            category=DiagnosticCategory.NABI_CONTEXT,
            severity=DiagnosticSeverity.INFO,
            title="NABI araştırma kapsamı",
            summary=(
                f"{covered} / {total} portföy sembolünde NABI araştırma kapsamı mevcut."
            ),
            evidence={
                "symbols_with_nabi_coverage": covered,
                "total_symbols": total,
                "symbols_without_coverage": missing,
            },
            metric_value=float(covered),
            threshold=None,
            affected_symbols=missing,
            confidence=DiagnosticConfidence.HIGH,
            source="nabi_intelligence_facade",
        )
    ]

    if decisions:
        diagnostics.append(
            PortfolioDiagnostic(
                code="NABI_DECISION_DISTRIBUTION",
                category=DiagnosticCategory.NABI_CONTEXT,
                severity=DiagnosticSeverity.INFO,
                title="NABI karar dağılımı",
                summary=(
                    "Mevcut NABI karar etiketlerinin portföy sembolleri arasındaki dağılımı "
                    "(bağlamsal bilgi; portföy değerlemesini değiştirmez)."
                ),
                evidence={"decision_counts": decisions},
                metric_value=float(sum(decisions.values())),
                threshold=None,
                affected_symbols=list(decisions.keys()),
                confidence=DiagnosticConfidence.HIGH,
                source="nabi_intelligence_facade",
            )
        )

    return diagnostics


def _sort_diagnostics(diagnostics: List[PortfolioDiagnostic]) -> List[PortfolioDiagnostic]:
    return sorted(
        diagnostics,
        key=lambda item: (
            _SEVERITY_ORDER[item.severity],
            item.category.value,
            item.code,
        ),
    )


def portfolio_data_quality_ok(
    portfolio_view: PortfolioIntelligenceView,
    *,
    transaction_history_complete: bool,
) -> bool:
    return (
        portfolio_view.health.priced_position_coverage_pct >= 100.0
        and portfolio_view.unpriced_position_count == 0
        and not portfolio_view.mixed_currency_warning
        and portfolio_view.foreign_currency_position_count == 0
        and transaction_history_complete
    )


def build_portfolio_diagnostics(
    *,
    portfolio_id: str,
    generated_at: str,
    portfolio_view: PortfolioIntelligenceView,
    performance_view: Optional[WealthPerformanceView] = None,
    benchmark_view: Optional[BenchmarkComparisonView] = None,
    performance_index_points: Optional[Sequence[Tuple[str, float]]] = None,
    transaction_history_complete: bool = True,
) -> PortfolioDiagnosticsView:
    comparable_performance = bool(
        performance_view
        and performance_view.linked_performance
        and performance_view.linked_performance.performance_comparable
    )
    benchmark_available = bool(
        benchmark_view and benchmark_view.performance_comparable
    )
    history_points = performance_view.history_points if performance_view else []

    diagnostics: List[PortfolioDiagnostic] = []
    diagnostics.extend(
        build_data_quality_diagnostics(
            portfolio_view=portfolio_view,
            performance_view=performance_view,
            benchmark_view=benchmark_view,
            transaction_history_complete=transaction_history_complete,
        )
    )
    diagnostics.extend(build_concentration_diagnostics(portfolio_view))
    diagnostics.extend(build_diversification_diagnostics(portfolio_view))
    diagnostics.extend(build_cash_diagnostics(portfolio_view))
    diagnostics.extend(build_pl_structure_diagnostics(portfolio_view))
    diagnostics.extend(
        build_drawdown_diagnostics(
            history_points=history_points,
            performance_index_points=performance_index_points,
            comparable_performance=comparable_performance,
        )
    )
    diagnostics.extend(build_benchmark_diagnostics(benchmark_view))
    diagnostics.extend(build_nabi_context_diagnostics(portfolio_view))

    ordered = _sort_diagnostics(diagnostics)
    high_count = sum(1 for item in ordered if item.severity == DiagnosticSeverity.HIGH)
    watch_count = sum(1 for item in ordered if item.severity == DiagnosticSeverity.WATCH)
    info_count = sum(1 for item in ordered if item.severity == DiagnosticSeverity.INFO)

    return PortfolioDiagnosticsView(
        portfolio_id=portfolio_id,
        generated_at=generated_at,
        diagnostics=ordered,
        high_count=high_count,
        watch_count=watch_count,
        info_count=info_count,
        data_quality_ok=portfolio_data_quality_ok(
            portfolio_view,
            transaction_history_complete=transaction_history_complete,
        ),
        comparable_performance=comparable_performance,
        benchmark_available=benchmark_available,
    )
