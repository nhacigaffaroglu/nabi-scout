from __future__ import annotations

from statistics import median
from typing import Iterable, Optional, Tuple

from services.decision_outcome_contract import (
    OUTCOME_STATUS_COMPLETE,
    OUTCOME_STATUS_PARTIAL,
    OUTCOME_STATUS_UNRESOLVED,
    DecisionLearningInsight,
    DecisionOutcome,
    DecisionScorecard,
)
from services.participation_filter_service import PARTICIPATION_UNKNOWN

MIN_LEARNING_SAMPLE = 2
PSYCHOLOGY_TERMS = frozenset({
    "fomo",
    "korku",
    "açgözlülük",
    "fear",
    "greed",
    "panik",
})


def build_decision_scorecard(outcomes: Iterable[DecisionOutcome]) -> DecisionScorecard:
    rows = tuple(outcomes)
    total = len(rows)
    positive = negative = neutral = unresolved = 0
    evidence_complete = 0
    pct_values: list[float] = []
    thesis_aligned = 0
    with_invalidation = 0
    without_rationale = 0
    kontrol_et = 0
    limited_research = 0
    limitations: list[str] = []

    for row in rows:
        if row.outcome_status == OUTCOME_STATUS_UNRESOLVED:
            unresolved += 1
        if row.outcome_status in {OUTCOME_STATUS_COMPLETE, OUTCOME_STATUS_PARTIAL}:
            evidence_complete += 1
        if row.percentage_outcome is not None:
            pct_values.append(row.percentage_outcome)
            if row.percentage_outcome > 0.5:
                positive += 1
            elif row.percentage_outcome < -0.5:
                negative += 1
            else:
                neutral += 1
        if row.thesis_at_decision:
            thesis_aligned += 1
        else:
            without_rationale += 1
        if row.invalidation_conditions_at_decision:
            with_invalidation += 1
        status = str(row.participation_status_at_decision or "")
        if "kontrol et" in status.lower():
            kontrol_et += 1
        if status in {PARTICIPATION_UNKNOWN, "", "Değerlendirilmedi"}:
            limited_research += 1

    if total == 0:
        limitations.append("Değerlendirilecek karar kaydı yok.")

    return DecisionScorecard(
        total_evaluated=total,
        positive_outcomes=positive,
        negative_outcomes=negative,
        neutral_outcomes=neutral,
        unresolved_decisions=unresolved,
        evidence_complete_count=evidence_complete,
        evidence_complete_pct=(evidence_complete / total * 100.0) if total else None,
        average_outcome_pct=(sum(pct_values) / len(pct_values)) if pct_values else None,
        median_outcome_pct=median(pct_values) if pct_values else None,
        thesis_aligned_count=thesis_aligned,
        with_invalidation_conditions=with_invalidation,
        without_journal_rationale=without_rationale,
        kontrol_et_decisions=kontrol_et,
        limited_research_decisions=limited_research,
        limitations=tuple(limitations),
    )


def _insight(
    *,
    insight_type: str,
    evidence_count: int,
    severity: str,
    description: str,
    supporting_decision_ids: Tuple[str, ...],
    evidence_completeness: str,
    limitation: str,
) -> DecisionLearningInsight:
    return DecisionLearningInsight(
        insight_type=insight_type,
        evidence_count=evidence_count,
        severity=severity,
        description=description,
        supporting_decision_ids=supporting_decision_ids,
        evidence_completeness=evidence_completeness,
        limitation=limitation,
    )


def build_decision_learning_insights(
    *,
    outcomes: Iterable[DecisionOutcome],
    journal_entries: Iterable[dict],
) -> Tuple[DecisionLearningInsight, ...]:
    outcome_rows = tuple(outcomes)
    entries = tuple(journal_entries)
    insights: list[DecisionLearningInsight] = []

    concentration_adds = [
        row for row in outcome_rows
        if row.decision_type in {"increased_position", "initiated_position"}
        and row.quantity_at_decision is not None
    ]
    if len(concentration_adds) >= MIN_LEARNING_SAMPLE:
        ids = tuple(row.journal_id for row in concentration_adds[:8])
        insights.append(
            _insight(
                insight_type="repeated_position_additions",
                evidence_count=len(concentration_adds),
                severity="watch",
                description=(
                    f"{len(concentration_adds)} karar kaydı pozisyon ekleme/artırma "
                    "bağlamında; yoğunlaşma eğilimini gözden geçirin."
                ),
                supporting_decision_ids=ids,
                evidence_completeness="ledger_linked" if any(
                    row.decision_price is not None for row in concentration_adds
                ) else "partial",
                limitation="Psikolojik yorum yapılmaz; yalnızca kayıtlı karar desenleri.",
            )
        )

    limited_research = [
        row for row in outcome_rows
        if not row.thesis_at_decision and not row.research_reference
    ]
    if len(limited_research) >= MIN_LEARNING_SAMPLE:
        insights.append(
            _insight(
                insight_type="decisions_without_rationale",
                evidence_count=len(limited_research),
                severity="info",
                description=(
                    f"{len(limited_research)} karar kaydında tez veya araştırma "
                    "referansı eksik."
                ),
                supporting_decision_ids=tuple(row.journal_id for row in limited_research[:8]),
                evidence_completeness="journal_only",
                limitation="Eksik alanlar kanıt boşluğu olarak raporlanır.",
            )
        )

    kontrol_et = [
        row for row in outcome_rows
        if row.participation_status_at_decision
        and "kontrol et" in str(row.participation_status_at_decision).lower()
    ]
    if kontrol_et:
        insights.append(
            _insight(
                insight_type="kontrol_et_decisions",
                evidence_count=len(kontrol_et),
                severity="high",
                description=(
                    f"{len(kontrol_et)} karar 'Kontrol Et' katılım durumundaki "
                    "varlıklarla ilişkili."
                ),
                supporting_decision_ids=tuple(row.journal_id for row in kontrol_et[:8]),
                evidence_completeness="participation_snapshot",
                limitation="Katılım durumu karar anındaki kayıtlı değerdir.",
            )
        )

    short_hold: list[DecisionOutcome] = []
    for row in outcome_rows:
        if row.decision_type == "initiated_position" and row.holding_period_days is not None:
            if row.holding_period_days <= 30 and row.decision_type != "closed_position":
                pass
        if row.decision_type == "closed_position" and row.holding_period_days is not None:
            if row.holding_period_days <= 30:
                short_hold.append(row)
    if len(short_hold) >= MIN_LEARNING_SAMPLE:
        insights.append(
            _insight(
                insight_type="short_holding_period_closes",
                evidence_count=len(short_hold),
                severity="watch",
                description=(
                    f"{len(short_hold)} kapanış kararı 30 günden kısa tutma "
                    "süresiyle ilişkili."
                ),
                supporting_decision_ids=tuple(row.journal_id for row in short_hold[:8]),
                evidence_completeness="partial",
                limitation="Tutma süresi karar tarihi ile değerlendirme anı arasındadır.",
            )
        )

    no_invalidation = [
        entry for entry in entries
        if entry.get("action_context") in {"added", "increased"}
        and not entry.get("invalidation_conditions")
    ]
    if len(no_invalidation) >= MIN_LEARNING_SAMPLE:
        insights.append(
            _insight(
                insight_type="missing_invalidation_conditions",
                evidence_count=len(no_invalidation),
                severity="info",
                description=(
                    f"{len(no_invalidation)} ekleme/artırma kararında geçersiz kılma "
                    "koşulu belirtilmemiş."
                ),
                supporting_decision_ids=tuple(
                    str(entry.get("id") or "") for entry in no_invalidation[:8]
                ),
                evidence_completeness="journal_only",
                limitation="Yalnızca kayıtlı alanlar değerlendirilir.",
            )
        )

    return tuple(insights)


def contains_psychological_inference(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in PSYCHOLOGY_TERMS)
