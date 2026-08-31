from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.fund_analysis_contract import FundAnalysisResult
from services.symbol_resolver_service import (
    SECURITY_TYPE_UNRESOLVED,
    ResolvedSecurity,
)
from services.turkiye_fund_snapshot_reader import is_turkiye_fund_production_identity

FUND_REPORT_SESSION_SYMBOL = "fund_report_symbol"
FUND_REPORT_SESSION_LIVE = "fund_report_live"
FUND_REPORT_SESSION_RESOLVED = "fund_report_resolved"
FUND_REPORT_SESSION_INSTRUMENT = "fund_report_instrument"
FUND_REPORT_SESSION_MARKET = "fund_report_market"
FUND_REPORT_QUERY_PARAM = "fund_symbol"
FUND_REPORT_QUERY_INSTRUMENT = "fund_instrument"
FUND_REPORT_QUERY_MARKET = "fund_market"

from services.participation_intelligence_contract import PARTICIPATION_DISCLAIMER_SHORT

SHARIAH_DISCLAIMER = PARTICIPATION_DISCLAIMER_SHORT
LIVE_DATA_PROMPT = (
    "Canlı veri yok. Ayrıntılar için «Canlı veriyi yenile» kullanın."
)
COLD_OPEN_BANNER = (
    "Takip metadata görünür. Canlı portföy, performans ve risk için "
    "«Canlı veriyi yenile» kullanın."
)
UNTRACKED_WHILE_OPEN_MESSAGE = "Bu fon artık takip listesinde değil."


@dataclass(frozen=True)
class TurkiyeFundReportCanonical:
    participation_status: str
    research_allowed: bool
    fi_score: Optional[float]
    fi_state: str
    exposure: Optional[str]
    geography: Optional[str]
    eight_e: str
    increase_allowed: bool
    methodology_id: str
    methodology_version: str
    as_of_key: str
    source_as_of: Dict[str, Any]
    instrument: str = "FUND"
    market: str = "TR"


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
    canonical: Optional[TurkiyeFundReportCanonical] = None
    canonical_unavailable_reason: Optional[str] = None
    instrument: Optional[str] = None
    market: Optional[str] = None


def normalize_fund_report_symbol(symbol: Optional[str]) -> str:
    return str(symbol or "").strip().upper()


def resolve_requested_symbol(
    *,
    session_symbol: Optional[str],
    query_symbol: Optional[str],
) -> str:
    return normalize_fund_report_symbol(session_symbol or query_symbol)


def _normalize_identity_part(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip().upper()
    return text or None


def resolve_requested_identity(
    *,
    session_symbol: Optional[str],
    query_symbol: Optional[str],
    session_instrument: Optional[str] = None,
    query_instrument: Optional[str] = None,
    session_market: Optional[str] = None,
    query_market: Optional[str] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    symbol = resolve_requested_symbol(
        session_symbol=session_symbol,
        query_symbol=query_symbol,
    )
    instrument = _normalize_identity_part(session_instrument or query_instrument)
    market = _normalize_identity_part(session_market or query_market)
    return symbol, instrument, market


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

    if is_turkiye_fund_production_identity(normalized):
        return True, None

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
    if is_turkiye_fund_production_identity(normalized):
        from services.turkiye_fund_navigation import turkiye_fund_nav_display_name

        catalog_name = turkiye_fund_nav_display_name(normalized)
        if catalog_name:
            return catalog_name
    return normalized


def turkiye_fund_report_canonical_from_read(read: Any) -> TurkiyeFundReportCanonical:
    quality = dict(read.fund_intelligence.raw_row.get("data_quality") or {})
    source_as_of = dict(quality.get("source_as_of") or {})
    return TurkiyeFundReportCanonical(
        participation_status=read.participation.status,
        research_allowed=bool(read.participation.research_allowed),
        fi_score=read.fund_intelligence.score,
        fi_state=read.fund_intelligence.state,
        exposure=read.fund_intelligence.exposure.primary_exposure,
        geography=read.fund_intelligence.exposure.geography,
        eight_e=read.decision.decision,
        increase_allowed=bool(read.decision.exposure_increase_allowed),
        methodology_id=read.participation.methodology_id,
        methodology_version=read.participation.methodology_version,
        as_of_key=read.fund_intelligence.as_of_key,
        source_as_of=source_as_of,
    )


def build_fund_report_view(
    symbol: str,
    *,
    tracked_row: Optional[Dict[str, Any]],
    live_result: Optional[FundAnalysisResult] = None,
    resolved: Optional[ResolvedSecurity] = None,
    analysis_kind: Optional[str] = None,
    had_tracked_context: bool = False,
    candidate_row: Optional[Dict[str, Any]] = None,
    canonical: Optional[TurkiyeFundReportCanonical] = None,
    canonical_unavailable_reason: Optional[str] = None,
    instrument: Optional[str] = None,
    market: Optional[str] = None,
) -> FundReportViewModel:
    normalized = normalize_fund_report_symbol(symbol)
    turkiye_identity = is_turkiye_fund_production_identity(
        normalized,
        instrument=instrument,
        market=market,
    )
    if turkiye_identity:
        matched_live = None
        matched_resolved = None
        analysis_kind = None
    else:
        matched_live = merge_live_result_for_symbol(normalized, live_result)
        matched_resolved = merge_resolved_for_symbol(normalized, resolved)
    is_tracked = tracked_row is not None
    has_live_data = matched_live is not None
    view_instrument = "FUND" if turkiye_identity else _normalize_identity_part(instrument)
    view_market = "TR" if turkiye_identity else _normalize_identity_part(market)

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
    if entry_allowed and is_tracked and not has_live_data and not turkiye_identity:
        state_messages.append(COLD_OPEN_BANNER)
    if entry_allowed and had_tracked_context and not is_tracked and not turkiye_identity:
        state_messages.append(UNTRACKED_WHILE_OPEN_MESSAGE)
    if entry_allowed and not is_tracked and has_live_data and not turkiye_identity:
        state_messages.append("Bu fon takip listesinde değil.")

    if entry_allowed and canonical is not None:
        state_messages.append("Canonical snapshot state. Fresh TEFAS/KAP compute is not used.")
    if entry_allowed and canonical_unavailable_reason:
        state_messages.append(
            "Canonical snapshot unavailable: "
            f"{canonical_unavailable_reason}. Live recompute is blocked."
        )

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
        canonical=canonical,
        canonical_unavailable_reason=canonical_unavailable_reason,
        instrument=view_instrument,
        market=view_market,
    )
