from __future__ import annotations

from typing import Any, Dict, Optional

from services.fund_analysis_contract import FundAnalysisResult
from services.fund_tracking_contract import _now_iso
from services.symbol_resolver_service import (
    SECURITY_TYPE_UNRESOLVED,
    ResolvedSecurity,
)

METADATA_MERGE_FIELDS = frozenset({
    "fund_name",
    "exchange",
    "asset_class",
    "participation_status",
    "participation_score",
    "participation_source",
    "data_provider",
    "resolution_source",
})


def build_tracked_fund_payload(
    fund_result: FundAnalysisResult,
    resolved: ResolvedSecurity,
) -> Dict[str, Any]:
    return {
        "symbol": fund_result.symbol,
        "fund_name": fund_result.fund_name or resolved.company_name,
        "exchange": fund_result.exchange or resolved.exchange,
        "asset_class": fund_result.asset_class,
        "participation_status": fund_result.participation_status,
        "participation_score": fund_result.participation_score,
        "participation_source": fund_result.participation_source,
        "data_provider": fund_result.data_provider,
        "resolution_source": resolved.resolution_source,
    }


def _normalize_symbol(symbol: Optional[str]) -> str:
    return str(symbol or "").strip().upper()


def _has_meaningful_fund_name(symbol: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return text.upper() != _normalize_symbol(symbol)


def _prefer_fund_name(
    symbol: str,
    existing: Any,
    incoming: Any,
) -> Optional[str]:
    existing_text = str(existing or "").strip()
    incoming_text = str(incoming or "").strip()
    existing_meaningful = _has_meaningful_fund_name(symbol, existing_text)
    incoming_meaningful = _has_meaningful_fund_name(symbol, incoming_text)

    if incoming_meaningful and not existing_meaningful:
        return incoming_text
    if existing_meaningful and not incoming_meaningful:
        return existing_text
    if incoming_meaningful and existing_meaningful:
        return incoming_text if len(incoming_text) >= len(existing_text) else existing_text
    if incoming_text:
        return incoming_text
    if existing_text:
        return existing_text
    return None


def merge_tracked_fund_metadata(
    existing_row: Optional[Dict[str, Any]],
    fund_result: FundAnalysisResult,
    resolved: ResolvedSecurity,
) -> Dict[str, Any]:
    incoming = build_tracked_fund_payload(fund_result, resolved)
    symbol = _normalize_symbol(incoming.get("symbol"))
    merged: Dict[str, Any] = {"symbol": symbol}

    for field in METADATA_MERGE_FIELDS:
        existing_value = (existing_row or {}).get(field)
        incoming_value = incoming.get(field)
        if field == "fund_name":
            chosen = _prefer_fund_name(symbol, existing_value, incoming_value)
        elif incoming_value is None or incoming_value == "":
            chosen = existing_value
        else:
            chosen = incoming_value
        if chosen is not None and chosen != "":
            merged[field] = chosen

    return merged


def save_tracked_fund(
    tracked_fund_repo,
    *,
    fund_result: FundAnalysisResult,
    resolved: ResolvedSecurity,
) -> Dict[str, Any]:
    if resolved.security_type == SECURITY_TYPE_UNRESOLVED or not resolved.is_etf:
        raise ValueError("Bu sembol güvenilir biçimde fon/ETF olarak doğrulanmadı; takibe alınamaz.")
    if fund_result.analysis_kind != "fund":
        raise ValueError("Yalnızca fon analizi sonuçları takibe alınabilir.")
    payload = build_tracked_fund_payload(fund_result, resolved)
    return tracked_fund_repo.upsert_by_symbol(payload)


def refresh_tracked_fund_metadata(
    tracked_fund_repo,
    *,
    fund_result: FundAnalysisResult,
    resolved: ResolvedSecurity,
) -> Dict[str, Any]:
    if resolved.security_type == SECURITY_TYPE_UNRESOLVED or not resolved.is_etf:
        raise ValueError("Bu sembol güvenilir biçimde fon/ETF olarak doğrulanmadı.")
    if fund_result.analysis_kind != "fund":
        raise ValueError("Yalnızca fon analizi sonuçları güncellenebilir.")

    existing = tracked_fund_repo.get_by_symbol(fund_result.symbol)
    if existing is None:
        raise ValueError("Takip kaydı bulunamadı.")

    payload = merge_tracked_fund_metadata(existing, fund_result, resolved)
    payload["last_reviewed_at"] = _now_iso()
    return tracked_fund_repo.upsert_by_symbol(
        payload,
        touch_last_reviewed=False,
    )


def untrack_fund(tracked_fund_repo, *, symbol: str) -> bool:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return False
    return tracked_fund_repo.delete_by_symbol(normalized)
