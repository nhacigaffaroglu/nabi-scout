from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.ui_formatters import format_research_status

RESEARCH_WORKFLOW_STATUSES = (
    "YENI",
    "INCELEMEDE",
    "BEKLEMEDE",
    "TEKRAR_BAK",
    "TAMAMLANDI",
)

DEFAULT_RESEARCH_STATUS = "YENI"

LEGACY_RESEARCH_STATUS_MAP: Dict[str, str] = {
    "Araştırılacak": "YENI",
    "İnceleniyor": "INCELEMEDE",
    "Tamamlandı": "TAMAMLANDI",
    "Arşiv": "TAMAMLANDI",
    "Otomatik tarandı": "YENI",
}

WORKFLOW_FILTER_ALL = "Tümü"
WORKFLOW_FILTER_OPEN = "Açık araştırmalar"
WORKFLOW_FILTER_INCELEMEDE = "İnceliyorum"
WORKFLOW_FILTER_TEKRAR_BAK = "Tekrar bak"
WORKFLOW_FILTER_BEKLEMEDE = "Beklemede"
WORKFLOW_FILTER_TAMAMLANDI = "Tamamlandı"

WORKFLOW_FILTER_OPTIONS = (
    WORKFLOW_FILTER_ALL,
    WORKFLOW_FILTER_OPEN,
    WORKFLOW_FILTER_INCELEMEDE,
    WORKFLOW_FILTER_TEKRAR_BAK,
    WORKFLOW_FILTER_BEKLEMEDE,
    WORKFLOW_FILTER_TAMAMLANDI,
)

_UNSET = object()


class ResearchWorkflowError(ValueError):
    """Invalid workflow status or payload."""


class ResearchWorkflowSchemaError(RuntimeError):
    """Workflow columns missing; migration required."""


def normalize_research_status(value: Optional[str]) -> str:
    if value is None:
        return DEFAULT_RESEARCH_STATUS

    text = str(value).strip()
    if not text:
        return DEFAULT_RESEARCH_STATUS

    if text in RESEARCH_WORKFLOW_STATUSES:
        return text

    mapped = LEGACY_RESEARCH_STATUS_MAP.get(text)
    if mapped:
        return mapped

    lowered = text.casefold()
    if lowered.startswith("scanner v") and lowered.endswith("tarandı"):
        return DEFAULT_RESEARCH_STATUS

    return DEFAULT_RESEARCH_STATUS


def validate_research_status(value: str) -> str:
    text = str(value).strip()
    if text not in RESEARCH_WORKFLOW_STATUSES:
        raise ResearchWorkflowError(f"Geçersiz araştırma durumu: {value}")
    return text


def is_open_research_status(value: Optional[str]) -> bool:
    return normalize_research_status(value) != "TAMAMLANDI"


def build_research_workflow(candidate: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    candidate = candidate or {}
    status = normalize_research_status(candidate.get("research_status"))
    return {
        "research_status": status,
        "research_status_label": format_research_status(status),
        "research_next_action": candidate.get("research_next_action"),
        "research_note": candidate.get("research_note"),
        "last_reviewed_at": candidate.get("last_reviewed_at"),
        "is_open": is_open_research_status(status),
    }


def build_research_workflow_update(
    *,
    status: Optional[str] = None,
    next_action: Optional[str] = _UNSET,
    research_note: Optional[str] = _UNSET,
    last_reviewed_at: Optional[datetime] = _UNSET,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}

    if status is not None:
        payload["research_status"] = validate_research_status(status)

    if next_action is not _UNSET:
        payload["research_next_action"] = _clean_optional_text(next_action)

    if research_note is not _UNSET:
        payload["research_note"] = _clean_optional_text(research_note)

    if last_reviewed_at is not _UNSET:
        if last_reviewed_at is None:
            payload["last_reviewed_at"] = None
        else:
            reviewed = last_reviewed_at
            if reviewed.tzinfo is None:
                reviewed = reviewed.replace(tzinfo=timezone.utc)
            payload["last_reviewed_at"] = reviewed.isoformat()

    if not payload:
        raise ResearchWorkflowError("Güncellenecek workflow alanı yok.")

    return payload


def attach_workflow_context(entry: Dict[str, Any]) -> Dict[str, Any]:
    candidate = entry.get("candidate") or {}
    workflow = build_research_workflow(candidate)
    enriched = dict(entry)
    enriched.update(workflow)
    return enriched


def filter_monitor_entries(
    entries: List[Dict[str, Any]],
    workflow_filter: str,
) -> List[Dict[str, Any]]:
    if workflow_filter == WORKFLOW_FILTER_ALL:
        return list(entries)

    filtered: List[Dict[str, Any]] = []
    for entry in entries:
        workflow = build_research_workflow(entry.get("candidate") or {})
        status = workflow["research_status"]

        if workflow_filter == WORKFLOW_FILTER_OPEN and workflow["is_open"]:
            filtered.append(entry)
        elif workflow_filter == WORKFLOW_FILTER_INCELEMEDE and status == "INCELEMEDE":
            filtered.append(entry)
        elif workflow_filter == WORKFLOW_FILTER_TEKRAR_BAK and status == "TEKRAR_BAK":
            filtered.append(entry)
        elif workflow_filter == WORKFLOW_FILTER_BEKLEMEDE and status == "BEKLEMEDE":
            filtered.append(entry)
        elif workflow_filter == WORKFLOW_FILTER_TAMAMLANDI and status == "TAMAMLANDI":
            filtered.append(entry)

    return filtered


def workflow_select_options() -> List[tuple[str, str]]:
    return [
        (format_research_status(status), status)
        for status in RESEARCH_WORKFLOW_STATUSES
    ]


def workflow_select_index(current_status: Optional[str]) -> int:
    normalized = normalize_research_status(current_status)
    try:
        return RESEARCH_WORKFLOW_STATUSES.index(normalized)
    except ValueError:
        return 0


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
