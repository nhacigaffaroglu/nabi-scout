from __future__ import annotations

from typing import Any, Dict

from services.fund_analysis_contract import FundAnalysisResult
from services.symbol_resolver_service import (
    SECURITY_TYPE_UNRESOLVED,
    ResolvedSecurity,
)


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


def untrack_fund(tracked_fund_repo, *, symbol: str) -> bool:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return False
    return tracked_fund_repo.delete_by_symbol(normalized)
