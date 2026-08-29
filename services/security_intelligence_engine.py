"""Deterministic Security Intelligence engine.

Reuses NABI Score v4 scale/inverse bands for overlapping metrics.
Does not default missing values to 50. Does not include portfolio fit.
Does not call an LLM.
"""

from __future__ import annotations

from typing import Iterable, Optional

from services.nabi_score_v4 import inverse, scale
from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.security_intelligence_contract import (
    CHANGE_BALANCE_SHEET_IMPROVING,
    CHANGE_BALANCE_SHEET_WEAKENING,
    CHANGE_DATA_QUALITY_CHANGED,
    CHANGE_GROWTH_ACCELERATING,
    CHANGE_GROWTH_SLOWING,
    CHANGE_MARGIN_COMPRESSING,
    CHANGE_MARGIN_EXPANDING,
    CHANGE_MOMENTUM_STRENGTHENING,
    CHANGE_MOMENTUM_WEAKENING,
    CHANGE_PARTICIPATION_CHANGED,
    CHANGE_QUALITY_DETERIORATING,
    CHANGE_QUALITY_IMPROVING,
    CHANGE_RISK_DECREASING,
    CHANGE_RISK_INCREASING,
    CHANGE_VALUATION_DETERIORATING,
    CHANGE_VALUATION_IMPROVING,
    DIM_BALANCE_SHEET,
    DIM_DATA_QUALITY,
    DIM_GROWTH,
    DIM_MOMENTUM,
    DIM_PROFITABILITY,
    DIM_QUALITY,
    DIM_RISK,
    DIM_VALUATION,
    DimensionResult,
    SecurityFacts,
    SecurityIntelligenceSnapshot,
    SecurityIntelligenceView,
    SecurityParticipationContext,
    snapshot_from_view,
    STATE_ATTRACTIVE,
    STATE_AVOID,
    STATE_CAUTION,
    STATE_INSUFFICIENT_DATA,
    STATE_NEUTRAL,
    STATE_WATCH,
    STATUS_INSUFFICIENT_DATA,
    STATUS_NEUTRAL,
    STATUS_STRONG,
    STATUS_VERY_STRONG,
    STATUS_VERY_WEAK,
    STATUS_WEAK,
)

_CORE_DIMENSIONS = (
    DIM_QUALITY,
    DIM_GROWTH,
    DIM_PROFITABILITY,
    DIM_BALANCE_SHEET,
    DIM_VALUATION,
)

_OVERALL_WEIGHTS = {
    DIM_QUALITY: 0.22,
    DIM_GROWTH: 0.18,
    DIM_PROFITABILITY: 0.16,
    DIM_BALANCE_SHEET: 0.16,
    DIM_VALUATION: 0.16,
    DIM_MOMENTUM: 0.06,
    DIM_RISK: 0.06,
}

_MIN_CORE_SCORED = 3
_CHANGE_SCORE_DELTA = 5.0


def _present(value: Optional[float]) -> bool:
    return value is not None


def weighted_or_none(items: Iterable[tuple[Optional[float], float]]) -> Optional[float]:
    available = [(float(value), weight) for value, weight in items if value is not None]
    if not available:
        return None
    weight_sum = sum(weight for _, weight in available)
    if weight_sum <= 0:
        return None
    return sum(value * weight for value, weight in available) / weight_sum


def status_from_score(score: Optional[float]) -> str:
    if score is None:
        return STATUS_INSUFFICIENT_DATA
    if score >= 80:
        return STATUS_VERY_STRONG
    if score >= 65:
        return STATUS_STRONG
    if score >= 45:
        return STATUS_NEUTRAL
    if score >= 30:
        return STATUS_WEAK
    return STATUS_VERY_WEAK


def _confidence(used: int, required: int) -> float:
    if required <= 0:
        return 0.0
    return round(100.0 * used / required, 1)


def _dimension(
    name: str,
    items: list[tuple[str, Optional[float], float]],
    *,
    extra_reasons: tuple[str, ...] = (),
) -> DimensionResult:
    used = [label for label, value, _weight in items if _present(value)]
    missing = [label for label, value, _weight in items if not _present(value)]
    score = weighted_or_none([(value, weight) for _label, value, weight in items])
    if score is not None:
        score = round(score, 1)
    reasons = list(extra_reasons)
    if score is None:
        reasons.append("INSUFFICIENT_FACTS")
    return DimensionResult(
        name=name,
        score=score,
        status=status_from_score(score),
        confidence=_confidence(len(used), len(items)),
        facts_used=tuple(used),
        missing_facts=tuple(missing),
        reason_codes=tuple(reasons),
    )


def _quality(facts: SecurityFacts) -> DimensionResult:
    return _dimension(
        DIM_QUALITY,
        [
            ("roic", scale(facts.roic, 5, 25), 0.50),
            ("roe", scale(facts.roe, 8, 28), 0.30),
            ("roa", scale(facts.roa, 3, 14), 0.20),
        ],
    )


def _growth(facts: SecurityFacts) -> DimensionResult:
    return _dimension(
        DIM_GROWTH,
        [
            ("revenue_cagr_3y", scale(facts.revenue_cagr_3y, 0, 18), 0.28),
            ("eps_cagr_3y", scale(facts.eps_cagr_3y, 0, 22), 0.28),
            ("fcf_cagr_3y", scale(facts.fcf_cagr_3y, 0, 22), 0.24),
            ("revenue_growth_yoy", scale(facts.revenue_growth_yoy, -5, 22), 0.10),
            ("eps_growth_yoy", scale(facts.eps_growth_yoy, -10, 28), 0.10),
        ],
    )


def _profitability(facts: SecurityFacts) -> DimensionResult:
    return _dimension(
        DIM_PROFITABILITY,
        [
            ("roic", scale(facts.roic, 5, 25), 0.35),
            ("operating_margin", scale(facts.operating_margin, 5, 30), 0.25),
            ("fcf_margin", scale(facts.fcf_margin, 2, 22), 0.20),
            ("net_margin", scale(facts.net_margin, 2, 20), 0.10),
            ("gross_margin", scale(facts.gross_margin, 15, 65), 0.10),
        ],
    )


def _balance_sheet(facts: SecurityFacts) -> DimensionResult:
    return _dimension(
        DIM_BALANCE_SHEET,
        [
            ("current_ratio", scale(facts.current_ratio, 0.8, 2.2), 0.20),
            ("debt_to_equity", inverse(facts.debt_to_equity, 0.2, 2.2), 0.30),
            ("net_debt_to_fcf", inverse(facts.net_debt_to_fcf, 0, 5), 0.30),
            ("interest_coverage", scale(facts.interest_coverage, 2, 18), 0.20),
        ],
    )


def _valuation(facts: SecurityFacts) -> DimensionResult:
    extra: list[str] = []
    if facts.pe is not None and facts.pe > 40:
        extra.append("VALUATION_EXPENSIVE")
    elif facts.pe is not None and 0 < facts.pe <= 18:
        extra.append("VALUATION_ATTRACTIVE")
    return _dimension(
        DIM_VALUATION,
        [
            ("pe", inverse(facts.pe, 12, 40), 0.50),
            ("price_to_sales", inverse(facts.price_to_sales, 1.5, 10), 0.25),
            ("price_to_book", inverse(facts.price_to_book, 1.5, 10), 0.25),
        ],
        extra_reasons=tuple(extra),
    )


def _momentum(facts: SecurityFacts) -> DimensionResult:
    return _dimension(
        DIM_MOMENTUM,
        [
            ("return_3m", scale(facts.return_3m, -20, 20), 0.35),
            ("return_6m", scale(facts.return_6m, -25, 30), 0.25),
            ("return_1y", scale(facts.return_1y, -30, 40), 0.25),
            ("drawdown", inverse(facts.drawdown, 5, 45), 0.15),
        ],
    )


def _risk(facts: SecurityFacts) -> DimensionResult:
    extra: list[str] = []
    if facts.debt_to_equity is not None and facts.debt_to_equity > 3:
        extra.append("HIGH_LEVERAGE")
    if facts.interest_coverage is not None and facts.interest_coverage < 1.5:
        extra.append("WEAK_INTEREST_COVERAGE")
    if facts.fcf_margin is not None and facts.fcf_margin < 0:
        extra.append("NEGATIVE_FCF_MARGIN")
    return _dimension(
        DIM_RISK,
        [
            ("debt_to_equity", inverse(facts.debt_to_equity, 0.2, 2.8), 0.30),
            ("net_debt_to_fcf", inverse(facts.net_debt_to_fcf, 0, 7), 0.30),
            ("current_ratio", scale(facts.current_ratio, 0.7, 2.0), 0.20),
            ("interest_coverage", scale(facts.interest_coverage, 1.5, 15), 0.20),
        ],
        extra_reasons=tuple(extra),
    )


_DATA_QUALITY_FIELDS = (
    "price",
    "market_cap",
    "revenue",
    "free_cash_flow",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "roe",
    "roa",
    "roic",
    "revenue_growth_yoy",
    "eps_growth_yoy",
    "pe",
    "price_to_sales",
    "price_to_book",
    "debt_to_equity",
    "current_ratio",
    "interest_coverage",
    "return_3m",
    "return_1y",
)


def _data_quality(facts: SecurityFacts) -> DimensionResult:
    used = [name for name in _DATA_QUALITY_FIELDS if _present(getattr(facts, name))]
    missing = [name for name in _DATA_QUALITY_FIELDS if not _present(getattr(facts, name))]
    completeness = _confidence(len(used), len(_DATA_QUALITY_FIELDS))
    reasons: list[str] = []
    if facts.stale:
        reasons.append("STALE_DATA")
    if not used:
        reasons.append("NO_FACTUAL_INPUTS")
        score = None
    else:
        score = completeness
        if completeness < 50:
            reasons.append("LOW_COMPLETENESS")
    return DimensionResult(
        name=DIM_DATA_QUALITY,
        score=score,
        status=status_from_score(score),
        confidence=completeness,
        facts_used=tuple(used),
        missing_facts=tuple(missing),
        reason_codes=tuple(reasons),
    )


def _overall(dimensions: dict[str, DimensionResult]) -> tuple[Optional[float], str, float]:
    scored_core = sum(1 for name in _CORE_DIMENSIONS if dimensions[name].score is not None)
    items = [
        (dimensions[name].score, _OVERALL_WEIGHTS[name])
        for name in _OVERALL_WEIGHTS
        if dimensions[name].score is not None
    ]
    confidences = [dimensions[name].confidence for name in _CORE_DIMENSIONS]
    confidence = round(sum(confidences) / len(confidences), 1)
    if scored_core < _MIN_CORE_SCORED:
        return None, STATUS_INSUFFICIENT_DATA, confidence
    score = weighted_or_none(items)
    if score is None:
        return None, STATUS_INSUFFICIENT_DATA, confidence
    return round(score, 1), status_from_score(score), confidence


def _strengths(facts: SecurityFacts, dimensions: dict[str, DimensionResult]) -> tuple[str, ...]:
    items: list[str] = []
    if facts.roic is not None and facts.roic >= 15:
        items.append("ROIC_ABOVE_THRESHOLD")
    if facts.revenue_growth_yoy is not None and facts.revenue_growth_yoy > 0:
        items.append("REVENUE_GROWTH_POSITIVE")
    if facts.revenue_cagr_3y is not None and facts.revenue_cagr_3y >= 10:
        items.append("REVENUE_CAGR_STRONG")
    if facts.fcf_margin is not None and facts.fcf_margin >= 12:
        items.append("FCF_MARGIN_STRONG")
    if facts.debt_to_equity is not None and facts.debt_to_equity <= 0.8:
        items.append("BALANCE_SHEET_HEALTHY")
    if dimensions[DIM_VALUATION].status in {STATUS_STRONG, STATUS_VERY_STRONG}:
        items.append("VALUATION_SUPPORTIVE")
    return tuple(items[:6])


def _weaknesses(facts: SecurityFacts, dimensions: dict[str, DimensionResult]) -> tuple[str, ...]:
    items: list[str] = []
    if dimensions[DIM_VALUATION].status in {STATUS_WEAK, STATUS_VERY_WEAK}:
        items.append("VALUATION_ELEVATED")
    if facts.fcf_growth_yoy is not None and facts.fcf_growth_yoy < 0:
        items.append("FCF_GROWTH_NEGATIVE")
    if facts.revenue_cagr_3y is not None and facts.revenue_cagr_3y < 0:
        items.append("REVENUE_STRUCTURAL_DECLINE")
    if facts.operating_margin is not None and facts.operating_margin < 5:
        items.append("OPERATING_MARGIN_WEAK")
    if dimensions[DIM_GROWTH].status in {STATUS_WEAK, STATUS_VERY_WEAK}:
        items.append("GROWTH_WEAK")
    return tuple(items[:6])


def _risk_flags(facts: SecurityFacts, risk: DimensionResult) -> tuple[str, ...]:
    flags = list(risk.reason_codes)
    if facts.stale:
        flags.append("STALE_DATA")
    if "INSUFFICIENT_FACTS" in flags:
        flags.remove("INSUFFICIENT_FACTS")
    return tuple(dict.fromkeys(flags))


def resolve_investment_state(
    *,
    participation_status: str,
    research_allowed: Optional[bool],
    overall_status: str,
) -> tuple[str, bool]:
    """Investable only when Uygun, research_allowed, and ATTRACTIVE."""
    status = str(participation_status or "").strip()
    allowed = research_allowed is True
    if status == PARTICIPATION_STATUS_UYGUN_DEGIL:
        return STATE_AVOID, False
    if status == PARTICIPATION_STATUS_KONTROL_ET or not allowed:
        if overall_status == STATUS_INSUFFICIENT_DATA:
            return STATE_INSUFFICIENT_DATA, False
        return STATE_CAUTION, False
    if status != PARTICIPATION_STATUS_UYGUN or not allowed:
        return STATE_CAUTION, False
    if overall_status == STATUS_INSUFFICIENT_DATA:
        return STATE_INSUFFICIENT_DATA, False
    if overall_status in {STATUS_VERY_STRONG, STATUS_STRONG}:
        return STATE_ATTRACTIVE, True
    if overall_status == STATUS_NEUTRAL:
        return STATE_WATCH, False
    if overall_status == STATUS_WEAK:
        return STATE_CAUTION, False
    if overall_status == STATUS_VERY_WEAK:
        return STATE_AVOID, False
    return STATE_INSUFFICIENT_DATA, False


def compare_snapshots(
    previous: Optional[SecurityIntelligenceSnapshot],
    current: SecurityIntelligenceSnapshot,
) -> tuple[str, ...]:
    if previous is None:
        return ()
    flags: list[str] = []

    def _moved(name: str, up: str, down: str) -> None:
        before = (previous.dimension_scores or {}).get(name)
        after = (current.dimension_scores or {}).get(name)
        if before is None or after is None:
            return
        delta = after - before
        if delta >= _CHANGE_SCORE_DELTA:
            flags.append(up)
        elif delta <= -_CHANGE_SCORE_DELTA:
            flags.append(down)

    _moved(DIM_QUALITY, CHANGE_QUALITY_IMPROVING, CHANGE_QUALITY_DETERIORATING)
    _moved(DIM_GROWTH, CHANGE_GROWTH_ACCELERATING, CHANGE_GROWTH_SLOWING)
    _moved(DIM_PROFITABILITY, CHANGE_MARGIN_EXPANDING, CHANGE_MARGIN_COMPRESSING)
    _moved(DIM_BALANCE_SHEET, CHANGE_BALANCE_SHEET_IMPROVING, CHANGE_BALANCE_SHEET_WEAKENING)
    _moved(DIM_VALUATION, CHANGE_VALUATION_IMPROVING, CHANGE_VALUATION_DETERIORATING)
    _moved(DIM_MOMENTUM, CHANGE_MOMENTUM_STRENGTHENING, CHANGE_MOMENTUM_WEAKENING)
    _moved(DIM_RISK, CHANGE_RISK_DECREASING, CHANGE_RISK_INCREASING)
    if previous.participation_status != current.participation_status:
        flags.append(CHANGE_PARTICIPATION_CHANGED)
    prev_dq = (previous.dimension_scores or {}).get(DIM_DATA_QUALITY)
    curr_dq = (current.dimension_scores or {}).get(DIM_DATA_QUALITY)
    if prev_dq is not None and curr_dq is not None and abs(curr_dq - prev_dq) >= _CHANGE_SCORE_DELTA:
        flags.append(CHANGE_DATA_QUALITY_CHANGED)
    return tuple(flags)


def evaluate_security_intelligence(
    facts: SecurityFacts,
    participation: Optional[SecurityParticipationContext] = None,
    *,
    previous: Optional[SecurityIntelligenceSnapshot] = None,
) -> SecurityIntelligenceView:
    participation = participation or SecurityParticipationContext()
    dimensions = {
        DIM_QUALITY: _quality(facts),
        DIM_GROWTH: _growth(facts),
        DIM_PROFITABILITY: _profitability(facts),
        DIM_BALANCE_SHEET: _balance_sheet(facts),
        DIM_VALUATION: _valuation(facts),
        DIM_MOMENTUM: _momentum(facts),
        DIM_RISK: _risk(facts),
        DIM_DATA_QUALITY: _data_quality(facts),
    }
    overall_score, overall_status, overall_confidence = _overall(dimensions)
    if facts.stale and overall_status != STATUS_INSUFFICIENT_DATA:
        # Stale facts stay scored but cannot look stronger than NEUTRAL.
        if overall_status in {STATUS_VERY_STRONG, STATUS_STRONG}:
            overall_status = STATUS_NEUTRAL
    state, investable = resolve_investment_state(
        participation_status=participation.status,
        research_allowed=participation.research_allowed,
        overall_status=overall_status,
    )
    draft = SecurityIntelligenceView(
        symbol=facts.symbol,
        quality=dimensions[DIM_QUALITY],
        growth=dimensions[DIM_GROWTH],
        profitability=dimensions[DIM_PROFITABILITY],
        balance_sheet=dimensions[DIM_BALANCE_SHEET],
        valuation=dimensions[DIM_VALUATION],
        momentum=dimensions[DIM_MOMENTUM],
        risk=dimensions[DIM_RISK],
        data_quality=dimensions[DIM_DATA_QUALITY],
        overall_score=overall_score,
        overall_status=overall_status,
        overall_confidence=overall_confidence,
        strengths=_strengths(facts, dimensions),
        weaknesses=_weaknesses(facts, dimensions),
        risk_flags=_risk_flags(facts, dimensions[DIM_RISK]),
        change_flags=(),
        participation_status=participation.status,
        research_allowed=participation.research_allowed,
        investment_state=state,
        investable=investable,
    )
    if previous is None:
        return draft
    change_flags = compare_snapshots(previous, snapshot_from_view(draft, as_of=facts.as_of))
    return SecurityIntelligenceView(
        symbol=draft.symbol,
        quality=draft.quality,
        growth=draft.growth,
        profitability=draft.profitability,
        balance_sheet=draft.balance_sheet,
        valuation=draft.valuation,
        momentum=draft.momentum,
        risk=draft.risk,
        data_quality=draft.data_quality,
        overall_score=draft.overall_score,
        overall_status=draft.overall_status,
        overall_confidence=draft.overall_confidence,
        strengths=draft.strengths,
        weaknesses=draft.weaknesses,
        risk_flags=draft.risk_flags,
        change_flags=change_flags,
        participation_status=draft.participation_status,
        research_allowed=draft.research_allowed,
        investment_state=draft.investment_state,
        investable=draft.investable,
        engine_version=draft.engine_version,
        facts_version=draft.facts_version,
    )
