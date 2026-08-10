from __future__ import annotations

from typing import Any, Dict, List, Optional

DECISION_WEIGHTS = {
    "YÜKSEK ÖNCELİKLİ ARAŞTIRMA ADAYI": 30,
    "ARAŞTIRMA ADAYI": 25,
    "İZLE": 10,
    "İKİNCİL İNCELEME": 5,
    "VERİ EKSİK — ÖN ELEME": 8,
    "ŞİMDİLİK UZAK DUR": 0,
}

FRESHNESS_WEIGHTS = {
    "STALE": 10,
    "AGING": 5,
    "UNKNOWN": 3,
    "FRESH": 0,
}

AVAILABILITY_CATEGORIES = frozenset({"AVAILABILITY"})


def compute_research_priority(
    candidate: Dict[str, Any],
    *,
    recent_change: Optional[Dict[str, Any]] = None,
    is_user_watchlist: bool = False,
    is_first_seen: bool = False,
) -> Dict[str, Any]:
    components: Dict[str, float] = {}
    reasons: List[str] = []
    seen_reasons: set[str] = set()

    def add_reason(message: str) -> None:
        if message and message not in seen_reasons:
            seen_reasons.add(message)
            reasons.append(message)

    decision_label = candidate.get("decision_label")
    decision_weight = DECISION_WEIGHTS.get(decision_label or "", 0)
    if decision_weight:
        components["decision_label"] = float(decision_weight)
        if decision_label:
            add_reason(str(decision_label))

    change = recent_change or {}
    change_score = float(change.get("change_score") or 0)
    changes = change.get("changes") or []
    has_high = any(item.get("severity") == "HIGH" for item in changes)

    if has_high:
        components["recent_change"] = 25.0
        add_reason(_primary_change_reason(changes, default="Son taramada önemli değişiklik"))
    elif change_score >= 15:
        components["recent_change"] = 12.0
        add_reason(_primary_change_reason(changes, default="Son taramada orta düzey değişiklik"))
    elif change_score >= 5:
        components["recent_change"] = 5.0
        add_reason(_primary_change_reason(changes, default="Son taramada düşük düzey değişiklik"))

    if is_first_seen:
        components["first_seen"] = 8.0
        add_reason("Yeni takip edilen şirket")

    if is_user_watchlist:
        components["user_watchlist"] = 10.0
        add_reason("Kullanıcı izleme listesinde")

    freshness_status = candidate.get("freshness_status") or "UNKNOWN"
    freshness_weight = FRESHNESS_WEIGHTS.get(freshness_status, 0)
    if freshness_weight:
        components["freshness_status"] = float(freshness_weight)
        if freshness_status == "STALE":
            add_reason("Finansal veri güncel değil — doğrulama gerekir")
        elif freshness_status == "AGING":
            add_reason("Finansal dönem eskiyor — doğrulama gerekebilir")
        elif freshness_status == "UNKNOWN":
            add_reason("Finansal dönem doğrulanamadı")

    opportunity_score = _as_float(candidate.get("opportunity_score"))
    if opportunity_score is not None:
        opportunity_component = min(
            8.0,
            max(0.0, (opportunity_score - 50.0) / 6.0),
        )
        if opportunity_component > 0:
            components["opportunity_score"] = round(opportunity_component, 1)
            add_reason("Fırsat potansiyeli güçlü")

    research_confidence = _as_float(candidate.get("research_confidence"))
    if research_confidence is not None and research_confidence < 50:
        components["research_confidence"] = 5.0
        add_reason("Veri güveni düşük — ek doğrulama gerekir")

    conviction_score = _as_float(candidate.get("conviction_score"))
    if conviction_score is not None and conviction_score >= 70:
        components["conviction_score"] = 5.0
        add_reason("Yüksek conviction")

    priority_score = round(min(100.0, sum(components.values())), 1)
    if priority_score >= 70:
        priority_label = "YÜKSEK"
    elif priority_score >= 45:
        priority_label = "ORTA"
    else:
        priority_label = "DÜŞÜK"

    return {
        "priority_score": priority_score,
        "priority_label": priority_label,
        "reasons": reasons[:5],
        "components": components,
    }


def rank_priority_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(entry: Dict[str, Any]) -> tuple:
        candidate = entry.get("candidate") or {}
        recent_change = entry.get("recent_change") or {}
        return (
            -float(entry.get("priority_score") or 0),
            -float(recent_change.get("change_score") or 0),
            -float(candidate.get("conviction_score") or 0),
            str(candidate.get("symbol") or ""),
        )

    return sorted(entries, key=sort_key)


def _primary_change_reason(
    changes: List[Dict[str, Any]],
    *,
    default: str,
) -> str:
    for item in changes:
        category = item.get("category")
        message = item.get("message")
        if not message:
            continue
        if category in AVAILABILITY_CATEGORIES:
            return message
        if item.get("field") == "decision_label":
            return f"Karar etiketi değişti: {message}"
        if item.get("field") == "freshness_status":
            return message
    for item in changes:
        message = item.get("message")
        if message:
            return message
    return default


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
