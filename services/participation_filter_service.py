from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence, TypeVar

from services.participation_intelligence_contract import (
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
)

PARTICIPATION_UNKNOWN = "Bilinmiyor"

PARTICIPATION_FILTER_ALL = "Tümü"
PARTICIPATION_FILTER_UYGUN = "Uygun"
PARTICIPATION_FILTER_KONTROL_ET = "Kontrol Et"
PARTICIPATION_FILTER_UYGUN_DEGIL = "Uygun Değil"
PARTICIPATION_FILTER_UYGUN_ONLY = "Sadece uygun olanları göster"

COMPANY_REPORT_PARTICIPATION_FILTERS: Sequence[str] = (
    PARTICIPATION_FILTER_ALL,
    PARTICIPATION_FILTER_UYGUN,
    PARTICIPATION_FILTER_KONTROL_ET,
    PARTICIPATION_FILTER_UYGUN_DEGIL,
)

PORTFOLIO_PARTICIPATION_FILTERS: Sequence[str] = (
    PARTICIPATION_FILTER_ALL,
    PARTICIPATION_FILTER_UYGUN,
    PARTICIPATION_FILTER_KONTROL_ET,
    PARTICIPATION_FILTER_UYGUN_DEGIL,
    PARTICIPATION_FILTER_UYGUN_ONLY,
)

T = TypeVar("T")


def normalize_participation_status(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return PARTICIPATION_UNKNOWN
    if text in {
        PARTICIPATION_STATUS_UYGUN,
        PARTICIPATION_STATUS_KONTROL_ET,
        PARTICIPATION_STATUS_UYGUN_DEGIL,
    }:
        return text
    return PARTICIPATION_UNKNOWN


def candidate_participation_status(candidate: Optional[dict]) -> str:
    if not candidate:
        return PARTICIPATION_UNKNOWN
    return normalize_participation_status(candidate.get("participation_status"))


def matches_participation_filter(
    status: Optional[str],
    filter_key: str,
    *,
    uygun_only: bool = False,
) -> bool:
    normalized = normalize_participation_status(status)
    if uygun_only or filter_key == PARTICIPATION_FILTER_UYGUN_ONLY:
        return normalized == PARTICIPATION_STATUS_UYGUN
    if filter_key in {"", PARTICIPATION_FILTER_ALL}:
        return True
    if filter_key == PARTICIPATION_FILTER_UYGUN:
        return normalized == PARTICIPATION_STATUS_UYGUN
    if filter_key == PARTICIPATION_FILTER_KONTROL_ET:
        return normalized == PARTICIPATION_STATUS_KONTROL_ET
    if filter_key == PARTICIPATION_FILTER_UYGUN_DEGIL:
        return normalized == PARTICIPATION_STATUS_UYGUN_DEGIL
    return True


def filter_by_participation(
    rows: Iterable[T],
    *,
    status_getter: Callable[[T], Optional[str]],
    filter_key: str,
    uygun_only: bool = False,
) -> List[T]:
    return [
        row
        for row in rows
        if matches_participation_filter(
            status_getter(row),
            filter_key,
            uygun_only=uygun_only,
        )
    ]


def filter_candidates_by_participation(
    candidates: Iterable[dict],
    filter_key: str,
) -> List[dict]:
    return filter_by_participation(
        candidates,
        status_getter=candidate_participation_status,
        filter_key=filter_key,
    )
