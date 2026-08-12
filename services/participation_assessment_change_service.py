from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple


CHANGE_FIELD_LABELS: Tuple[Tuple[str, str], ...] = (
    ("status", "Durum"),
    ("methodology_id", "Metodoloji"),
    ("methodology_version", "Metodoloji sürümü"),
    ("financial_overall_outcome", "Finansal sonuç"),
    ("business_overall_outcome", "Faaliyet alanı sonucu"),
    ("confidence", "Güven"),
)


def _normalize_capabilities(value: Any) -> Tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(sorted(str(item) for item in value))
    return (str(value),)


def compare_participation_snapshots(
    previous: Optional[Mapping[str, Any]],
    current: Mapping[str, Any],
) -> Dict[str, Any]:
    if previous is None:
        return {
            "has_change": False,
            "is_first_snapshot": True,
            "changes": [],
            "summary": "İlk kayıt",
        }

    changes: List[Dict[str, Any]] = []
    for field, label in CHANGE_FIELD_LABELS:
        previous_value = previous.get(field)
        current_value = current.get(field)
        if previous_value != current_value:
            changes.append(
                {
                    "field": field,
                    "label": label,
                    "from": previous_value,
                    "to": current_value,
                }
            )

    previous_caps = _normalize_capabilities(previous.get("missing_capabilities"))
    current_caps = _normalize_capabilities(current.get("missing_capabilities"))
    if previous_caps != current_caps:
        changes.append(
            {
                "field": "missing_capabilities",
                "label": "Eksik yetenekler / kanıt",
                "from": list(previous_caps),
                "to": list(current_caps),
            }
        )

    summary = _build_change_summary(changes)
    return {
        "has_change": bool(changes),
        "is_first_snapshot": False,
        "changes": changes,
        "summary": summary,
    }


def _build_change_summary(changes: List[Dict[str, Any]]) -> str:
    if not changes:
        return "Önceki kayıtla aynı"
    labels = [change["label"] for change in changes[:3]]
    summary = ", ".join(labels)
    if len(changes) > 3:
        summary += f" (+{len(changes) - 3})"
    return summary


def annotate_history_with_changes(
    history: List[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    annotated: List[Dict[str, Any]] = []
    for index, row in enumerate(history):
        previous = history[index + 1] if index + 1 < len(history) else None
        change = compare_participation_snapshots(previous, row)
        annotated.append(
            {
                **dict(row),
                "change_from_previous": change,
            }
        )
    return annotated
