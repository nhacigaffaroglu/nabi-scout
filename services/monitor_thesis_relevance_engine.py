from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from services.monitor_contract import ThesisRelevanceView


def assess_thesis_relevance(
    *,
    symbol: Optional[str],
    event_summary: str,
    thesis_payload: Optional[Mapping[str, Any]],
    journal_entries: Sequence[Mapping[str, Any]],
) -> ThesisRelevanceView:
    sym = str(symbol or "").strip().upper()
    if not sym:
        return ThesisRelevanceView(
            relevance="none",
            thesis_status=None,
            thesis_confidence=None,
            invalidation_match=False,
            explanation="Sembol bağlamı yok.",
            journal_entry_count=0,
            limitations=("Sembol yok.",),
        )

    if thesis_payload is None:
        if journal_entries:
            return ThesisRelevanceView(
                relevance="review_recommended",
                thesis_status=None,
                thesis_confidence=None,
                invalidation_match=False,
                explanation="Sembol için karar günlüğü kaydı mevcut; olayın tez bağlamı gözden geçirilebilir.",
                journal_entry_count=len(journal_entries),
                limitations=("Tez kaydı yok.",),
            )
        return ThesisRelevanceView(
            relevance="none",
            thesis_status=None,
            thesis_confidence=None,
            invalidation_match=False,
            explanation="Bu sembol için kayıtlı yatırım tezi bulunamadı.",
            journal_entry_count=0,
            limitations=("Tez kaydı yok.",),
        )

    thesis_status = str(thesis_payload.get("thesis_status") or "") or None
    thesis_confidence = str(thesis_payload.get("confidence") or "") or None
    invalidations = [
        str(item.get("statement") or item.get("condition") or "")
        for item in (thesis_payload.get("invalidation_conditions") or [])
        if isinstance(item, dict)
    ]
    journal_conditions = [
        str(row.get("invalidation_conditions") or "")
        for row in journal_entries
        if row.get("invalidation_conditions")
    ]
    all_conditions = [cond for cond in invalidations + journal_conditions if cond.strip()]
    summary_lower = event_summary.lower()
    matched = any(
        any(token in summary_lower for token in cond.lower().split() if len(token) > 4)
        for cond in all_conditions
    )

    if matched:
        return ThesisRelevanceView(
            relevance="potential_invalidation",
            thesis_status=thesis_status,
            thesis_confidence=thesis_confidence,
            invalidation_match=True,
            explanation=(
                "Bu olay kayıtlı geçersizleşme koşullarından biriyle potansiyel olarak "
                "ilişkili olabilir. Otomatik tez geçersizliği iddiası yapılmaz."
            ),
            journal_entry_count=len(journal_entries),
        )

    if journal_entries:
        return ThesisRelevanceView(
            relevance="review_recommended",
            thesis_status=thesis_status,
            thesis_confidence=thesis_confidence,
            invalidation_match=False,
            explanation="Sembol için karar günlüğü kaydı mevcut; olayın tez bağlamı gözden geçirilebilir.",
            journal_entry_count=len(journal_entries),
        )

    if thesis_status:
        return ThesisRelevanceView(
            relevance="thesis_present",
            thesis_status=thesis_status,
            thesis_confidence=thesis_confidence,
            invalidation_match=False,
            explanation="Kayıtlı tez mevcut; doğrudan geçersizleşme eşleşmesi tespit edilmedi.",
            journal_entry_count=0,
        )

    return ThesisRelevanceView(
        relevance="none",
        thesis_status=thesis_status,
        thesis_confidence=thesis_confidence,
        invalidation_match=False,
        explanation="Tez etkisi bilinmiyor.",
        journal_entry_count=0,
    )
