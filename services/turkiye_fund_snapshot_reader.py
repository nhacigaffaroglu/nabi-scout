"""Snapshot-only read path for Turkish fund Participation and FI.

Reuses existing BIST/US repositories and hydrators:

  participation_assessment_snapshots
    → ParticipationAssessmentRepository
    → snapshot_from_row
  security_intelligence_snapshots
    → SecurityIntelligenceSnapshotRepository
    → snapshot_from_row
  → build_portfolio_security_context
  → evaluate_portfolio_security_decision

Does not call TEFAS, KAP, Participation methodology, or FI compute.
Does not write snapshots, persist 8E, or call New Money.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Mapping, Optional, Sequence

from services.fund_decision_readiness import TURKIYE_FUND_8E_INSTRUMENT, TURKIYE_FUND_8E_MARKET
from services.fund_product_contract import (
    FUND_EVAL_ENGINE_VERSION,
    FUND_EVAL_FACTS_VERSION,
    LAYER_CASH_LIKE,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION,
)
from services.hybrid_exposure_allocation_policy import HybridPortfolioMode
from services.participation_assessment_persistence_service import snapshot_from_row as participation_from_row
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_context_builder import (
    PortfolioSecuritySourceBundle,
    build_portfolio_security_context,
)
from services.portfolio_security_decision_contract import PortfolioSecurityDecision
from services.portfolio_security_decision_engine import evaluate_portfolio_security_decision
from services.security_intelligence_contract import (
    SecurityIntelligenceSnapshot,
    persisted_snapshot_is_stale,
)
from services.security_intelligence_snapshot_service import snapshot_from_row as fi_from_row
from services.turkiye_fund_persistence import FORBIDDEN_AIS_EXPOSURE
from services.wealth_contract import normalize_symbol

REASON_PARTICIPATION_MISSING = "PARTICIPATION_SNAPSHOT_MISSING"
REASON_FI_MISSING = "FI_SNAPSHOT_MISSING"
REASON_INCOMPATIBLE_METHODOLOGY = "INCOMPATIBLE_PARTICIPATION_METHODOLOGY"
REASON_INCOMPATIBLE_FI_VERSION = "INCOMPATIBLE_FI_VERSION"
REASON_STALE_FI = "STALE_FI_SNAPSHOT"
REASON_RESEARCH_NOT_ALLOWED = "RESEARCH_NOT_ALLOWED"
REASON_PARTICIPATION_NOT_UYGUN = "PARTICIPATION_NOT_UYGUN"
REASON_AIS_CASH_FIREWALL = "AIS_CASH_FIREWALL"
REASON_WRITE_BLOCKED = "SNAPSHOT_READ_ONLY"

PARTICIPATION_SELECTION_RULE = (
    "latest assessed_at among rows whose methodology_id/version equal "
    f"{METHODOLOGY_TURKIYE_FUND_PARTICIPATION}/{METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION}"
)
FI_SELECTION_RULE = (
    "latest as_of among rows whose (facts_version, engine_version) equal "
    f"({FUND_EVAL_FACTS_VERSION}, {FUND_EVAL_ENGINE_VERSION}); "
    "identity is (symbol, as_of_key, facts_version, engine_version)"
)


class SnapshotReadError(Exception):
    def __init__(self, reason: str, *, fund_code: str = "") -> None:
        self.reason = reason
        self.fund_code = fund_code
        super().__init__(f"{fund_code}:{reason}" if fund_code else reason)


class ReadOnlyRepository:
    """Reject writes. Delegates reads to the underlying repository."""

    _BLOCKED = frozenset({"append_snapshot", "upsert", "insert", "update", "delete"})

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.blocked: list[str] = []

    def __getattr__(self, name: str):
        if name in self._BLOCKED:
            def _blocked(*_args: Any, **_kwargs: Any) -> Any:
                self.blocked.append(name)
                raise SnapshotReadError(REASON_WRITE_BLOCKED)

            return _blocked
        return getattr(self._inner, name)


@dataclass(frozen=True)
class TurkiyeFundParticipationRead:
    fund_code: str
    row_id: Optional[str]
    status: str
    research_allowed: Optional[bool]
    methodology_id: str
    methodology_version: str
    semantic_identity: str
    snapshot: Dict[str, Any]
    raw_row: Dict[str, Any]


@dataclass(frozen=True)
class TurkiyeFundEconomicExposureRead:
    primary_exposure: Optional[str]
    geography: Optional[str]
    confidence: Optional[str]
    lookthrough_weights: tuple[tuple[Any, ...], ...] = ()


@dataclass(frozen=True)
class TurkiyeFundIntelligenceRead:
    fund_code: str
    row_id: Optional[str]
    score: Optional[float]
    state: str
    completeness: Optional[float]
    confidence: Optional[float]
    as_of_key: str
    facts_version: str
    engine_version: str
    exposure: TurkiyeFundEconomicExposureRead
    snapshot: SecurityIntelligenceSnapshot
    raw_row: Dict[str, Any]


@dataclass(frozen=True)
class TurkiyeFundCanonicalRead:
    fund_code: str
    participation: TurkiyeFundParticipationRead
    fund_intelligence: TurkiyeFundIntelligenceRead
    decision: PortfolioSecurityDecision


def _history(repo: Any, symbol: str) -> list[Dict[str, Any]]:
    if hasattr(repo, "get_recent_history"):
        return [dict(row) for row in (repo.get_recent_history(symbol, limit=25) or [])]
    latest = repo.get_latest(symbol) if hasattr(repo, "get_latest") else None
    return [dict(latest)] if latest else []


def _applicable_participation_row(repo: Any, fund_code: str) -> Dict[str, Any]:
    history = _history(repo, fund_code)
    if not history:
        raise SnapshotReadError(REASON_PARTICIPATION_MISSING, fund_code=fund_code)
    for row in history:
        if (
            str(row.get("methodology_id") or "") == METHODOLOGY_TURKIYE_FUND_PARTICIPATION
            and str(row.get("methodology_version") or "")
            == METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION
        ):
            return row
    raise SnapshotReadError(REASON_INCOMPATIBLE_METHODOLOGY, fund_code=fund_code)


def _applicable_fi_row(repo: Any, fund_code: str) -> Dict[str, Any]:
    history = _history(repo, fund_code)
    if not history:
        raise SnapshotReadError(REASON_FI_MISSING, fund_code=fund_code)
    matched = None
    stale = False
    for row in history:
        if (
            str(row.get("facts_version") or "") != FUND_EVAL_FACTS_VERSION
            or str(row.get("engine_version") or "") != FUND_EVAL_ENGINE_VERSION
        ):
            continue
        if persisted_snapshot_is_stale(fi_from_row(row)):
            stale = True
            continue
        matched = row
        break
    if matched is not None:
        return matched
    if stale:
        raise SnapshotReadError(REASON_STALE_FI, fund_code=fund_code)
    raise SnapshotReadError(REASON_INCOMPATIBLE_FI_VERSION, fund_code=fund_code)


def _exposure_from_quality(quality: Mapping[str, Any]) -> TurkiyeFundEconomicExposureRead:
    nested = dict(quality.get("economic_exposure") or {})
    weights = tuple(
        tuple(item) if isinstance(item, (list, tuple)) else (item,)
        for item in (nested.get("lookthrough_weights") or ())
    )
    return TurkiyeFundEconomicExposureRead(
        primary_exposure=nested.get("primary_exposure"),
        geography=nested.get("geography"),
        confidence=nested.get("confidence"),
        lookthrough_weights=weights,
    )


def _assert_ais_cash_like(fund_code: str, exposure: TurkiyeFundEconomicExposureRead) -> None:
    if fund_code != "AIS":
        return
    primary = exposure.primary_exposure
    if primary in FORBIDDEN_AIS_EXPOSURE or primary != LAYER_CASH_LIKE:
        raise SnapshotReadError(REASON_AIS_CASH_FIREWALL, fund_code=fund_code)


def read_participation_snapshot(repo: Any, fund_code: str) -> TurkiyeFundParticipationRead:
    code = normalize_symbol(fund_code)
    row = _applicable_participation_row(repo, code)
    hydrated = participation_from_row(row)
    return TurkiyeFundParticipationRead(
        fund_code=code,
        row_id=str(row["id"]) if row.get("id") is not None else None,
        status=str(hydrated.get("status") or ""),
        research_allowed=hydrated.get("research_allowed"),
        methodology_id=str(hydrated.get("methodology_id") or ""),
        methodology_version=str(hydrated.get("methodology_version") or ""),
        semantic_identity=str(hydrated.get("semantic_identity") or ""),
        snapshot=hydrated,
        raw_row=dict(row),
    )


def read_fund_intelligence_snapshot(repo: Any, fund_code: str) -> TurkiyeFundIntelligenceRead:
    code = normalize_symbol(fund_code)
    row = _applicable_fi_row(repo, code)
    snap = fi_from_row(row)
    quality = dict(snap.data_quality or {})
    if quality.get("si_data_quality") and not any(
        quality.get(key) for key in ("status", "freshness_status", "overall")
    ):
        quality["status"] = quality["si_data_quality"]
        snap = replace(snap, data_quality=quality)
    exposure = _exposure_from_quality(quality)
    _assert_ais_cash_like(code, exposure)
    return TurkiyeFundIntelligenceRead(
        fund_code=code,
        row_id=str(row["id"]) if row.get("id") is not None else None,
        score=snap.overall_score,
        state=str(snap.investment_state or snap.overall_status or ""),
        completeness=quality.get("completeness"),
        confidence=snap.overall_confidence,
        as_of_key=str(row.get("as_of_key") or ""),
        facts_version=str(snap.facts_version or ""),
        engine_version=str(snap.engine_version or ""),
        exposure=exposure,
        snapshot=snap,
        raw_row=dict(row),
    )


def snapshot_bundle(
    participation: TurkiyeFundParticipationRead,
    fund_intelligence: TurkiyeFundIntelligenceRead,
    *,
    is_holding: bool = False,
    portfolio_weight: Optional[float] = None,
) -> PortfolioSecuritySourceBundle:
    exposure_ready = bool(fund_intelligence.exposure.primary_exposure)
    return PortfolioSecuritySourceBundle(
        snapshot=participation.snapshot,
        si_snapshot=fund_intelligence.snapshot,
        instrument_type=TURKIYE_FUND_8E_INSTRUMENT,
        market=TURKIYE_FUND_8E_MARKET,
        quantity=1.0 if is_holding else None,
        portfolio_weight=portfolio_weight,
        economic_exposure_status=(
            HybridPortfolioMode.STRICT.value
            if exposure_ready
            else HybridPortfolioMode.UNAVAILABLE.value
        ),
        as_of=fund_intelligence.snapshot.as_of,
    )


def evaluate_snapshot_fund_decision(
    participation: TurkiyeFundParticipationRead,
    fund_intelligence: TurkiyeFundIntelligenceRead,
    *,
    is_holding: bool = False,
    portfolio_weight: Optional[float] = None,
) -> PortfolioSecurityDecision:
    context = build_portfolio_security_context(
        participation.fund_code,
        snapshot_bundle(
            participation,
            fund_intelligence,
            is_holding=is_holding,
            portfolio_weight=portfolio_weight,
        ),
    )
    return evaluate_portfolio_security_decision(context)


def read_turkiye_fund_canonical(
    *,
    participation_repo: Any,
    snapshot_repo: Any,
    fund_code: str,
    is_holding: bool = False,
    portfolio_weight: Optional[float] = None,
) -> TurkiyeFundCanonicalRead:
    code = normalize_symbol(fund_code)
    participation = read_participation_snapshot(participation_repo, code)
    if participation.status != PARTICIPATION_STATUS_UYGUN:
        raise SnapshotReadError(REASON_PARTICIPATION_NOT_UYGUN, fund_code=code)
    if participation.research_allowed is not True:
        raise SnapshotReadError(REASON_RESEARCH_NOT_ALLOWED, fund_code=code)
    fund_intelligence = read_fund_intelligence_snapshot(snapshot_repo, code)
    decision = evaluate_snapshot_fund_decision(
        participation,
        fund_intelligence,
        is_holding=is_holding,
        portfolio_weight=portfolio_weight,
    )
    return TurkiyeFundCanonicalRead(
        fund_code=code,
        participation=participation,
        fund_intelligence=fund_intelligence,
        decision=decision,
    )


def read_pilot_canonical(
    *,
    participation_repo: Any,
    snapshot_repo: Any,
    fund_codes: Sequence[str] = ("AIS", "ZPE", "IAT"),
    is_holding: bool = False,
    portfolio_weight: Optional[float] = None,
) -> tuple[TurkiyeFundCanonicalRead, ...]:
    return tuple(
        read_turkiye_fund_canonical(
            participation_repo=participation_repo,
            snapshot_repo=snapshot_repo,
            fund_code=code,
            is_holding=is_holding,
            portfolio_weight=portfolio_weight,
        )
        for code in fund_codes
    )
