"""Candidate pipeline stage and score display. No scoring math."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)
from services.research_workflow_service import normalize_research_status

STAGE_DISCOVERED = "discovered"
STAGE_ONBOARDING = "onboarding"
STAGE_PARTICIPATION_CHECKED = "participation_checked"
STAGE_SCANNED = "scanned"
STAGE_RESEARCH_PENDING = "research_pending"
STAGE_FULLY_EVALUATED = "fully_evaluated"

STAGE_LABELS_TR = {
    STAGE_DISCOVERED: "Keşfedildi",
    STAGE_ONBOARDING: "Onboarding",
    STAGE_PARTICIPATION_CHECKED: "Katılım kontrol edildi",
    STAGE_SCANNED: "Tarandı",
    STAGE_RESEARCH_PENDING: "Araştırma bekliyor",
    STAGE_FULLY_EVALUATED: "Tam değerlendirildi",
}

ACTIONABLE_DECISIONS = frozenset({"GÜÇLÜ ADAY", "ADAY"})
INCOMPLETE_DECISIONS = frozenset({"VERİ EKSİK"})
NO_OPPORTUNITY_COPY = "Şu anda tam değerlendirmesi tamamlanmış güçlü bir fırsat yok."
SCORE_HIDDEN_COPY = "Analiz tamamlanmadığı için NABI Score gösterilmiyor."


def _text(value: Any) -> str:
    return str(value or "").strip()


def _participation_status(candidate: Mapping[str, Any]) -> str:
    return _text(candidate.get("participation_status"))


def _decision(candidate: Mapping[str, Any]) -> str:
    return _text(candidate.get("decision") or candidate.get("decision_label"))


def _completeness(candidate: Mapping[str, Any]) -> Optional[float]:
    raw = candidate.get("data_completeness")
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def has_valid_current_price(candidate: Mapping[str, Any]) -> bool:
    price = candidate.get("current_price")
    if price in (None, ""):
        return False
    try:
        return float(price) > 0
    except (TypeError, ValueError):
        return False


def participation_is_unresolved(candidate: Mapping[str, Any]) -> bool:
    status = _participation_status(candidate)
    return (not status) or status == PARTICIPATION_STATUS_KONTROL_ET


def participation_is_blocked(candidate: Mapping[str, Any]) -> bool:
    return _participation_status(candidate) == PARTICIPATION_STATUS_UYGUN_DEGIL


def participation_is_resolved(candidate: Mapping[str, Any]) -> bool:
    return _participation_status(candidate) in {
        PARTICIPATION_STATUS_UYGUN,
        PARTICIPATION_STATUS_UYGUN_DEGIL,
    }


def has_scan_evidence(candidate: Mapping[str, Any]) -> bool:
    if candidate.get("last_scanned_at") or candidate.get("scanner_version"):
        return True
    completeness = _completeness(candidate)
    if completeness is not None:
        return True
    decision = _decision(candidate)
    return bool(decision) and decision not in INCOMPLETE_DECISIONS


def analysis_is_incomplete(candidate: Mapping[str, Any]) -> bool:
    decision = _decision(candidate)
    if decision in INCOMPLETE_DECISIONS or not decision:
        return True
    completeness = _completeness(candidate)
    if completeness is not None and completeness < 50:
        return True
    if participation_is_unresolved(candidate):
        return True
    return not has_scan_evidence(candidate)


def nabi_score_is_displayable(candidate: Mapping[str, Any]) -> bool:
    """Hide numeric scores that would imply a finished analysis."""
    if analysis_is_incomplete(candidate):
        return False
    if candidate.get("nabi_score") in (None, ""):
        return False
    return True


def display_nabi_score(candidate: Mapping[str, Any]) -> Optional[float]:
    if not nabi_score_is_displayable(candidate):
        return None
    try:
        return float(candidate.get("nabi_score"))
    except (TypeError, ValueError):
        return None


def classify_candidate_pipeline_stage(candidate: Mapping[str, Any]) -> str:
    scanned = has_scan_evidence(candidate)
    resolved = participation_is_resolved(candidate)
    incomplete = analysis_is_incomplete(candidate)
    research_done = normalize_research_status(candidate.get("research_status")) == "TAMAMLANDI"
    source = _text(candidate.get("data_source")).lower()

    if not scanned and not resolved:
        if source == "universe_expansion" or participation_is_unresolved(candidate):
            if _decision(candidate) or source == "universe_expansion":
                return STAGE_ONBOARDING
        return STAGE_DISCOVERED

    if resolved and not scanned:
        return STAGE_PARTICIPATION_CHECKED

    if scanned and incomplete:
        return STAGE_SCANNED

    if scanned and not incomplete and not research_done:
        return STAGE_RESEARCH_PENDING

    if scanned and not incomplete and research_done:
        return STAGE_FULLY_EVALUATED

    if scanned:
        return STAGE_SCANNED
    return STAGE_DISCOVERED


def pipeline_stage_label(candidate: Mapping[str, Any]) -> str:
    return STAGE_LABELS_TR[classify_candidate_pipeline_stage(candidate)]


def is_actionable_opportunity(candidate: Mapping[str, Any]) -> bool:
    """Dashboard Fırsatlar eligibility. Numeric score alone is not enough."""
    if _decision(candidate) not in ACTIONABLE_DECISIONS:
        return False
    if not has_valid_current_price(candidate):
        return False
    if participation_is_blocked(candidate) or participation_is_unresolved(candidate):
        return False
    if analysis_is_incomplete(candidate):
        return False
    if classify_candidate_pipeline_stage(candidate) in {
        STAGE_DISCOVERED,
        STAGE_ONBOARDING,
    }:
        return False
    return True


def present_candidate_display_row(candidate: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(candidate)
    row["nabi_score"] = display_nabi_score(candidate)
    row["pipeline_stage"] = pipeline_stage_label(candidate)
    return row
