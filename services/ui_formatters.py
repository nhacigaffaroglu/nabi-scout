from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

LEGACY_HISTORY_NOTE = (
    "Eski taramalarda daha az alan kaydedildiği için geçmiş değişimlerin "
    "bir kısmı gösterilemeyebilir."
)

BADGE_LABELS: Dict[str, str] = {
    "NEW": "🆕 Yeni",
    "LEGACY_HISTORY": "🕘 Sınırlı geçmiş veri",
    "WATCHLIST": "⭐ İzleme listesinde",
    "DATA_ISSUE": "⚠️ Veri sorunu",
    "STALE": "🕒 Güncelliğini yitirmiş veri",
    "AGING": "⏳ Eskiyen veri",
    "UNKNOWN": "❓ Güncellik bilinmiyor",
    "UNKNOWN_FRESHNESS": "❓ Güncellik bilinmiyor",
    "DATA_AVAILABILITY": "📡 Veri geçici olarak erişilemedi",
}

FRESHNESS_LABELS: Dict[str, str] = {
    "FRESH": "Güncel",
    "STALE": "Güncelliğini yitirmiş",
    "AGING": "Eskiyor",
    "UNKNOWN": "Bilinmiyor",
}

PRIORITY_REASON_LABELS: Dict[str, str] = {
    "Yeni takip edilen şirket": "Bu zaman aralığında ilk kez göründü",
}

RESEARCH_STATUS_LABELS: Dict[str, str] = {
    "YENI": "Henüz başlanmadı",
    "INCELEMEDE": "İnceliyorum",
    "BEKLEMEDE": "Beklemede",
    "TEKRAR_BAK": "Tekrar bak",
    "TAMAMLANDI": "Tamamlandı",
}

MONTHS_TR = {
    1: "Oca",
    2: "Şub",
    3: "Mar",
    4: "Nis",
    5: "May",
    6: "Haz",
    7: "Tem",
    8: "Ağu",
    9: "Eyl",
    10: "Eki",
    11: "Kas",
    12: "Ara",
}


def format_badge(badge: Optional[str]) -> str:
    if not badge:
        return "—"
    return BADGE_LABELS.get(str(badge).strip(), str(badge))


def format_badges(badges: Optional[Sequence[str]]) -> List[str]:
    if not badges:
        return []
    return [format_badge(badge) for badge in badges]


def format_badges_compact(badges: Optional[Sequence[str]]) -> str:
    labels = format_badges(badges)
    return " · ".join(labels) if labels else ""


def format_research_status(value: Optional[str]) -> str:
    if not value:
        return RESEARCH_STATUS_LABELS["YENI"]
    key = str(value).strip().upper()
    return RESEARCH_STATUS_LABELS.get(key, RESEARCH_STATUS_LABELS["YENI"])


def format_freshness_label(value: Optional[str]) -> str:
    if not value:
        return "—"
    key = str(value).strip().upper()
    return FRESHNESS_LABELS.get(key, str(value))


def format_priority_reason(reason: Optional[str]) -> str:
    if not reason:
        return "—"
    return PRIORITY_REASON_LABELS.get(str(reason).strip(), str(reason))


def format_priority_reasons(reasons: Optional[Sequence[str]]) -> List[str]:
    if not reasons:
        return []
    return [format_priority_reason(reason) for reason in reasons]


def format_change_window_summary(
    window_change_score: Any,
    events: Optional[Sequence[Any]],
) -> str:
    visible_count = len(events or [])
    if visible_count == 0:
        return "Anlamlı değişiklik yok"

    score = int(window_change_score or 0)
    if visible_count == 1:
        count_label = "1 önemli değişiklik"
    else:
        count_label = f"{visible_count} önemli değişiklik"
    return f"Pencere değişim skoru: {score} · {count_label}"


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_date_tr(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        if value is None:
            return "—"
        text = str(value).strip()
        return text[:10] if len(text) >= 10 else text or "—"

    month = MONTHS_TR.get(parsed.month, str(parsed.month))
    return f"{parsed.day} {month} {parsed.year}"


def format_datetime_tr(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        if value is None:
            return "—"
        text = str(value).strip()
        return text[:10] if len(text) >= 10 else text or "—"

    return f"{format_date_tr(parsed)} · {parsed.strftime('%H:%M')} UTC"


def format_data_quality_notes(notes: Optional[Sequence[str]]) -> List[str]:
    if not notes:
        return []
    legacy_prefix = "Eski taramaların sınırlı snapshot"
    formatted: List[str] = []
    for note in notes:
        text = str(note)
        if text.startswith(legacy_prefix):
            formatted.append(LEGACY_HISTORY_NOTE)
        else:
            formatted.append(text)
    return formatted
