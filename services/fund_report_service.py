from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.fund_analysis_contract import FundAnalysisResult
from services.symbol_resolver_service import (
    SECURITY_TYPE_UNRESOLVED,
    ResolvedSecurity,
)

FUND_REPORT_SESSION_SYMBOL = "fund_report_symbol"
FUND_REPORT_SESSION_LIVE = "fund_report_live"
FUND_REPORT_SESSION_RESOLVED = "fund_report_resolved"
FUND_REPORT_QUERY_PARAM = "fund_symbol"

SHARIAH_DISCLAIMER = (
    "Bu bilgi bağımsız NABI Şeriat uygunluk doğrulaması değildir."
)
LIVE_DATA_PROMPT = (
    "Canlı veri yok. Ayrıntılar için «Canlı veriyi yenile» kullanın."
)
COLD_OPEN_BANNER = (
    "Takip metadata görünür. Canlı portföy, performans ve risk için "
    "«Canlı veriyi yenile» kullanın."
)
UNTRACKED_WHILE_OPEN_MESSAGE = "Bu fon artık takip listesinde değil."


@dataclass(frozen=True)
class FundReportViewModel:
    symbol: str
    fund_name: str
    tracked_row: Optional[Dict[str, Any]]
    live_result: Optional[FundAnalysisResult]
    resolved: Optional[ResolvedSecurity]
    is_tracked: bool
    has_live_data: bool
    entry_allowed: bool
    block_reason: Optional[str] = None
    state_messages: tuple[str, ...] = field(default_factory=tuple)


def normalize_fund_report_symbol(symbol: Optional[str]) -> str:
    return str(symbol or "").strip().upper()


def resolve_requested_symbol(
    *,
    session_symbol: Optional[str],
    query_symbol: Optional[str],
) -> str:
    return normalize_fund_report_symbol(session_symbol or query_symbol)


def is_valid_session_fund_handoff(
    symbol: str,
    *,
    analysis_kind: Optional[str],
    live_result: Optional[FundAnalysisResult],
    resolved: Optional[ResolvedSecurity],
) -> bool:
    normalized = normalize_fund_report_symbol(symbol)
    if not normalized:
        return False
    if live_result is None or resolved is None:
        return False
    effective_kind = analysis_kind or live_result.analysis_kind
    if effective_kind != "fund":
        return False
    if normalize_fund_report_symbol(live_result.symbol) != normalized:
        return False
    if normalize_fund_report_symbol(resolved.symbol) != normalized:
        return False
    if not resolved.is_etf:
        return False
    if resolved.security_type == SECURITY_TYPE_UNRESOLVED:
        return False
    if resolved.is_equity_eligible:
        return False
    return True


def validate_fund_report_entry(
    symbol: str,
    *,
    tracked_row: Optional[Dict[str, Any]],
    analysis_kind: Optional[str] = None,
    live_result: Optional[FundAnalysisResult] = None,
    resolved: Optional[ResolvedSecurity] = None,
) -> tuple[bool, Optional[str]]:
    normalized = normalize_fund_report_symbol(symbol)
    if not normalized:
        return False, "Sembol gerekli."

    if tracked_row is not None:
        return True, None

    if is_valid_session_fund_handoff(
        normalized,
        analysis_kind=analysis_kind,
        live_result=live_result,
        resolved=resolved,
    ):
        return True, None

    return False, (
        "Bu sembol için fon raporu açılamaz. "
        "Yalnızca takip edilen fonlar veya geçerli oturum fon analizi desteklenir."
    )


def merge_live_result_for_symbol(
    symbol: str,
    live_result: Optional[FundAnalysisResult],
) -> Optional[FundAnalysisResult]:
    normalized = normalize_fund_report_symbol(symbol)
    if not normalized or live_result is None:
        return None
    if normalize_fund_report_symbol(live_result.symbol) != normalized:
        return None
    return live_result


def merge_resolved_for_symbol(
    symbol: str,
    resolved: Optional[ResolvedSecurity],
) -> Optional[ResolvedSecurity]:
    normalized = normalize_fund_report_symbol(symbol)
    if not normalized or resolved is None:
        return None
    if normalize_fund_report_symbol(resolved.symbol) != normalized:
        return None
    return resolved


def _has_meaningful_fund_name(symbol: str, value: Optional[str]) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return text.upper() != normalize_fund_report_symbol(symbol)


def resolve_display_fund_name(
    symbol: str,
    *,
    tracked_row: Optional[Dict[str, Any]] = None,
    live_result: Optional[FundAnalysisResult] = None,
    candidate_row: Optional[Dict[str, Any]] = None,
) -> str:
    normalized = normalize_fund_report_symbol(symbol)
    candidates: List[str] = []
    for source in (
        (live_result.fund_name if live_result else None),
        (tracked_row or {}).get("fund_name"),
        (candidate_row or {}).get("company_name"),
    ):
        text = str(source or "").strip()
        if text:
            candidates.append(text)

    meaningful = [name for name in candidates if _has_meaningful_fund_name(normalized, name)]
    if meaningful:
        return max(meaningful, key=len)
    if candidates:
        return candidates[0]
    return normalized


def build_fund_report_view(
    symbol: str,
    *,
    tracked_row: Optional[Dict[str, Any]],
    live_result: Optional[FundAnalysisResult] = None,
    resolved: Optional[ResolvedSecurity] = None,
    analysis_kind: Optional[str] = None,
    had_tracked_context: bool = False,
    candidate_row: Optional[Dict[str, Any]] = None,
) -> FundReportViewModel:
    normalized = normalize_fund_report_symbol(symbol)
    matched_live = merge_live_result_for_symbol(normalized, live_result)
    matched_resolved = merge_resolved_for_symbol(normalized, resolved)
    is_tracked = tracked_row is not None
    has_live_data = matched_live is not None

    fund_name = resolve_display_fund_name(
        normalized,
        tracked_row=tracked_row,
        live_result=matched_live,
        candidate_row=candidate_row,
    )

    entry_allowed, block_reason = validate_fund_report_entry(
        normalized,
        tracked_row=tracked_row,
        analysis_kind=analysis_kind,
        live_result=matched_live,
        resolved=matched_resolved,
    )

    state_messages: List[str] = []
    if entry_allowed and is_tracked and not has_live_data:
        state_messages.append(COLD_OPEN_BANNER)
    if entry_allowed and had_tracked_context and not is_tracked:
        state_messages.append(UNTRACKED_WHILE_OPEN_MESSAGE)
    if entry_allowed and not is_tracked and has_live_data:
        state_messages.append("Bu fon takip listesinde değil.")

    return FundReportViewModel(
        symbol=normalized,
        fund_name=fund_name,
        tracked_row=tracked_row,
        live_result=matched_live,
        resolved=matched_resolved,
        is_tracked=is_tracked,
        has_live_data=has_live_data,
        entry_allowed=entry_allowed,
        block_reason=block_reason,
        state_messages=tuple(state_messages),
    )
