from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from services.fund_analysis_contract import FundAnalysisResult
from services.fund_analysis_service import analyze_fund
from services.fmp_client import FMPClient
from services.scan_runner_service import ScanRunResult, run_scan
from services.scan_universe_service import MANUAL_UNIVERSE_NAME
from services.symbol_resolver_service import (
    SECURITY_TYPE_UNRESOLVED,
    ResolvedSecurity,
    SymbolNotFoundError,
    normalize_symbol_input,
    participation_for_symbol,
    resolve_symbol,
)

UNRESOLVED_UNSUPPORTED_REASON = (
    "Varlık türü güvenilir biçimde doğrulanamadı; equity analizi çalıştırılmadı."
)


@dataclass
class ManualAnalysisResult:
    symbol: str
    analysis_kind: str
    resolved: ResolvedSecurity
    candidate: Optional[Dict[str, Any]] = None
    fund_result: Optional[FundAnalysisResult] = None
    scan_result: Optional[ScanRunResult] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    unsupported_reason: Optional[str] = None
    is_persisted: bool = False
    persisted_candidate_id: Optional[str] = None
    current_price: Optional[float] = None
    participation_status: Optional[str] = None
    participation_score: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["resolved"] = self.resolved.to_dict()
        if self.fund_result is not None:
            payload["fund_result"] = self.fund_result.to_dict()
        if self.scan_result is not None:
            payload["scan_result"] = {
                "run_id": self.scan_result.run_id,
                "universe_name": self.scan_result.universe_name,
                "status": self.scan_result.status,
                "updated": self.scan_result.updated,
            }
        return payload


def analyze_security(
    symbol: Optional[str],
    *,
    candidate_repo,
    scan_repo,
    fmp_client: FMPClient,
    sec_client,
    sec_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    nasdaq_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    engine=None,
) -> ManualAnalysisResult:
    normalized = normalize_symbol_input(symbol)
    if not normalized:
        raise SymbolNotFoundError("Sembol boş olamaz.")

    resolved = resolve_symbol(
        normalized,
        candidate_repo=candidate_repo,
        fmp_client=fmp_client,
        sec_lookup=sec_lookup,
        nasdaq_lookup=nasdaq_lookup,
    )
    existing = candidate_repo.get_by_symbol(normalized)
    is_persisted = existing is not None

    if resolved.is_etf:
        return _analyze_fund(
            resolved,
            fmp_client=fmp_client,
            is_persisted=is_persisted,
            persisted_candidate_id=(existing or {}).get("id"),
        )

    if not resolved.is_equity_eligible:
        return _analyze_unresolved(
            resolved,
            is_persisted=is_persisted,
            persisted_candidate_id=(existing or {}).get("id"),
        )

    return _analyze_equity(
        resolved,
        candidate_repo=candidate_repo,
        scan_repo=scan_repo,
        fmp_client=fmp_client,
        sec_client=sec_client,
        engine=engine,
        is_persisted=is_persisted,
        persisted_candidate_id=(existing or {}).get("id"),
    )


def save_manual_candidate(
    candidate_repo,
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    if not candidate:
        raise ValueError("Kaydedilecek aday bulunamadı.")
    if candidate.get("excluded"):
        raise ValueError("Elendi olarak işaretlenmiş sonuç aday havuzuna kaydedilemez.")
    security_type = str(candidate.get("security_type") or "").upper()
    if security_type in {"ETF", SECURITY_TYPE_UNRESOLVED} or candidate.get("is_etf"):
        raise ValueError("Bu sonuç aday havuzuna kaydedilemez.")

    return candidate_repo.upsert_by_symbol(candidate)


def _analyze_equity(
    resolved: ResolvedSecurity,
    *,
    candidate_repo,
    scan_repo,
    fmp_client: FMPClient,
    sec_client,
    engine,
    is_persisted: bool,
    persisted_candidate_id: Optional[str],
) -> ManualAnalysisResult:
    warnings: List[str] = []
    errors: List[str] = []

    if not resolved.cik:
        warnings.append("SEC CIK bulunamadı; analiz FMP verisiyle sınırlı olabilir.")

    participation_status, participation_score = participation_for_symbol(resolved.symbol)
    participation_defaults = {
        resolved.symbol: (participation_status, participation_score),
    }

    scan_result = run_scan(
        symbols=[resolved.to_scan_row()],
        universe_name=MANUAL_UNIVERSE_NAME,
        source="manual",
        scan_repo=scan_repo,
        candidate_repo=candidate_repo,
        fmp_client=fmp_client,
        sec_client=sec_client,
        engine=engine,
        participation_defaults=participation_defaults,
        inter_symbol_pause_seconds=0.0,
        persist_candidates=False,
    )

    candidate = scan_result.candidates[0] if scan_result.candidates else None
    if candidate is None:
        errors.append("Analiz sonucu üretilemedi.")

    if scan_result.fmp_rate_limited:
        warnings.append("FMP rate limit nedeniyle bazı veriler alınamadı.")

    return ManualAnalysisResult(
        symbol=resolved.symbol,
        analysis_kind="equity",
        resolved=resolved,
        candidate=candidate,
        scan_result=scan_result,
        warnings=warnings,
        errors=errors,
        is_persisted=is_persisted,
        persisted_candidate_id=persisted_candidate_id,
        current_price=_as_float((candidate or {}).get("current_price")),
        participation_status=participation_status,
        participation_score=participation_score,
    )


def _analyze_fund(
    resolved: ResolvedSecurity,
    *,
    fmp_client: FMPClient,
    is_persisted: bool,
    persisted_candidate_id: Optional[str],
) -> ManualAnalysisResult:
    fund_result = analyze_fund(resolved, fmp_client=fmp_client)
    return ManualAnalysisResult(
        symbol=resolved.symbol,
        analysis_kind="fund",
        resolved=resolved,
        fund_result=fund_result,
        warnings=list(fund_result.warnings),
        is_persisted=is_persisted,
        persisted_candidate_id=persisted_candidate_id,
        current_price=fund_result.current_price,
        participation_status=fund_result.participation_status,
        participation_score=fund_result.participation_score,
    )


def _analyze_unresolved(
    resolved: ResolvedSecurity,
    *,
    is_persisted: bool,
    persisted_candidate_id: Optional[str],
) -> ManualAnalysisResult:
    warnings: List[str] = []
    if resolved.classification_warning:
        warnings.append(resolved.classification_warning)
    return ManualAnalysisResult(
        symbol=resolved.symbol,
        analysis_kind="unresolved",
        resolved=resolved,
        candidate=None,
        warnings=warnings,
        unsupported_reason=UNRESOLVED_UNSUPPORTED_REASON,
        is_persisted=is_persisted,
        persisted_candidate_id=persisted_candidate_id,
    )


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
