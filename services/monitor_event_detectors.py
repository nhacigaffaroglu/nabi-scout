from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from services.monitor_contract import (
    EVENT_PARTICIPATION_REVIEW_REQUIRED,
    EVENT_PARTICIPATION_STATUS_CHANGED,
    EVENT_PORTFOLIO_VALUE_CHANGED,
    EVENT_PORTFOLIO_WEIGHT_CHANGED,
    EVENT_POSSIBLE_INVALIDATION_SIGNAL,
    EVENT_POSITION_CLOSED,
    EVENT_POSITION_OPENED,
    EVENT_RESEARCH_COVERAGE_CHANGED,
    EVENT_RESEARCH_STATUS_CHANGED,
    EVENT_SECTOR_ALLOCATION_CHANGED,
    EVENT_THESIS_CONFIDENCE_CHANGED,
    EVENT_THESIS_EVIDENCE_CHANGED,
    EVENT_THESIS_STATUS_CHANGED,
    MonitorEventDraft,
)
from services.monitor_dedupe import build_dedupe_key
from services.monitor_materiality_engine import apply_materiality_to_draft
from services.participation_assessment_change_service import compare_participation_snapshots
from services.portfolio_change_engine import compare_portfolio_snapshots
from services.investment_thesis_change_engine import detect_thesis_changes
from services.investment_thesis_service import thesis_view_from_dict
from services.wealth_timeline_contract import PortfolioSnapshotView


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _map_portfolio_code(code: str) -> str:
    mapping = {
        "NEW_HOLDING": EVENT_POSITION_OPENED,
        "CLOSED_HOLDING": EVENT_POSITION_CLOSED,
        "WEIGHT_CHANGE": EVENT_PORTFOLIO_WEIGHT_CHANGED,
        "PORTFOLIO_VALUE_CHANGE": EVENT_PORTFOLIO_VALUE_CHANGED,
        "SECTOR_ALLOCATION_CHANGE": EVENT_SECTOR_ALLOCATION_CHANGED,
        "RESEARCH_COVERAGE_CHANGE": EVENT_RESEARCH_COVERAGE_CHANGED,
    }
    return mapping.get(code, code)


def detect_portfolio_events(
    *,
    user_id: str,
    portfolio_id: str,
    previous: PortfolioSnapshotView,
    current: PortfolioSnapshotView,
) -> Tuple[MonitorEventDraft, ...]:
    drafts: List[MonitorEventDraft] = []
    occurred_at = current.captured_at or _now_iso()
    for change in compare_portfolio_snapshots(previous, current):
        event_type = _map_portfolio_code(change.code)
        symbol = change.affected_symbols[0] if change.affected_symbols else None
        dedupe = build_dedupe_key(
            "portfolio",
            user_id,
            portfolio_id,
            event_type,
            symbol or "portfolio",
            change.previous_value,
            change.metric_value,
            previous.captured_at[:10],
            current.captured_at[:10],
        )
        draft = MonitorEventDraft(
            user_id=user_id,
            portfolio_id=portfolio_id,
            symbol=symbol,
            event_type=event_type,
            event_category="portfolio",
            severity=change.severity,
            materiality="info",
            occurred_at=occurred_at,
            dedupe_key=dedupe,
            title=change.title,
            summary=change.detail,
            evidence_type="portfolio_snapshot",
            evidence_reference=f"{previous.id}:{current.id}",
            previous_value=str(change.previous_value) if change.previous_value is not None else None,
            current_value=str(change.metric_value) if change.metric_value is not None else None,
            absolute_change=change.metric_value,
            event_payload={
                "change_code": change.code,
                "affected_symbols": list(change.affected_symbols),
            },
        )
        weight = float(change.metric_value) if event_type == EVENT_PORTFOLIO_WEIGHT_CHANGED else None
        drafts.append(apply_materiality_to_draft(draft, portfolio_weight=weight))
    return tuple(drafts)


def detect_participation_events(
    *,
    symbol: str,
    previous_row: Optional[Dict[str, Any]],
    current_row: Dict[str, Any],
) -> Tuple[MonitorEventDraft, ...]:
    comparison = compare_participation_snapshots(previous_row, current_row)
    if not comparison.get("has_change"):
        return ()

    prev_status = str((previous_row or {}).get("status") or "")
    curr_status = str(current_row.get("status") or "")
    occurred_at = str(current_row.get("assessed_at") or _now_iso())
    dedupe = build_dedupe_key(
        "participation",
        symbol,
        "status",
        prev_status,
        curr_status,
        current_row.get("id"),
    )
    draft = MonitorEventDraft(
        user_id=None,
        portfolio_id=None,
        symbol=symbol,
        event_type=EVENT_PARTICIPATION_STATUS_CHANGED,
        event_category="participation",
        severity="watch",
        materiality="info",
        occurred_at=occurred_at,
        dedupe_key=dedupe,
        title=f"{symbol}: Katılım durumu değişti",
        summary=str(comparison.get("summary") or "Katılım durumu güncellendi."),
        evidence_type="participation_snapshot",
        evidence_reference=str(current_row.get("id") or ""),
        previous_value=prev_status or None,
        current_value=curr_status or None,
        event_payload={"changes": comparison.get("changes") or []},
    )
    draft = apply_materiality_to_draft(draft)
    if curr_status.lower() == "kontrol et":
        review_dedupe = build_dedupe_key("participation_review", symbol, curr_status, current_row.get("id"))
        review = MonitorEventDraft(
            user_id=None,
            portfolio_id=None,
            symbol=symbol,
            event_type=EVENT_PARTICIPATION_REVIEW_REQUIRED,
            event_category="participation",
            severity="watch",
            materiality="medium",
            occurred_at=occurred_at,
            dedupe_key=review_dedupe,
            title=f"{symbol}: Katılım incelemesi gerekli",
            summary="Katılım durumu 'Kontrol Et' olarak kayıtlı.",
            evidence_type="participation_snapshot",
            evidence_reference=str(current_row.get("id") or ""),
            current_value=curr_status,
            event_payload={"status": curr_status},
        )
        return (draft, apply_materiality_to_draft(review))
    return (draft,)


def detect_thesis_events(
    *,
    symbol: str,
    current_row: Dict[str, Any],
    previous_row: Optional[Dict[str, Any]],
) -> Tuple[MonitorEventDraft, ...]:
    if previous_row is None:
        return ()
    current_payload = current_row.get("thesis_payload") or current_row.get("payload") or {}
    previous_payload = previous_row.get("thesis_payload") or previous_row.get("payload") or {}
    if not isinstance(current_payload, dict) or not isinstance(previous_payload, dict):
        return ()
    try:
        current_view = thesis_view_from_dict(current_payload)
    except Exception:
        return ()
    changes = detect_thesis_changes(current_view, previous_payload)
    drafts: List[MonitorEventDraft] = []
    occurred_at = str(current_row.get("captured_at") or _now_iso())

    prev_status = str(previous_payload.get("thesis_status") or "")
    curr_status = str(current_payload.get("thesis_status") or "")
    if prev_status and curr_status and prev_status != curr_status:
        dedupe = build_dedupe_key("thesis_status", symbol, prev_status, curr_status, current_row.get("id"))
        draft = MonitorEventDraft(
            user_id=None,
            portfolio_id=None,
            symbol=symbol,
            event_type=EVENT_THESIS_STATUS_CHANGED,
            event_category="thesis",
            severity="watch",
            materiality="info",
            occurred_at=occurred_at,
            dedupe_key=dedupe,
            title=f"{symbol}: Tez durumu değişti",
            summary=f"Tez durumu {prev_status} → {curr_status}.",
            evidence_type="investment_thesis_snapshot",
            evidence_reference=str(current_row.get("id") or ""),
            previous_value=prev_status,
            current_value=curr_status,
            event_payload={"thesis_status": curr_status},
        )
        drafts.append(apply_materiality_to_draft(draft))

    prev_conf = str(previous_payload.get("confidence") or "")
    curr_conf = str(current_payload.get("confidence") or "")
    if prev_conf and curr_conf and prev_conf != curr_conf:
        dedupe = build_dedupe_key("thesis_confidence", symbol, prev_conf, curr_conf, current_row.get("id"))
        draft = MonitorEventDraft(
            user_id=None,
            portfolio_id=None,
            symbol=symbol,
            event_type=EVENT_THESIS_CONFIDENCE_CHANGED,
            event_category="thesis",
            severity="watch",
            materiality="info",
            occurred_at=occurred_at,
            dedupe_key=dedupe,
            title=f"{symbol}: Tez güveni değişti",
            summary=f"Tez güveni {prev_conf} → {curr_conf}.",
            evidence_type="investment_thesis_snapshot",
            evidence_reference=str(current_row.get("id") or ""),
            previous_value=prev_conf,
            current_value=curr_conf,
            event_payload={"confidence": curr_conf},
        )
        drafts.append(apply_materiality_to_draft(draft))

    for change in changes:
        dedupe = build_dedupe_key("thesis_evidence", symbol, change.code, change.statement, current_row.get("id"))
        draft = MonitorEventDraft(
            user_id=None,
            portfolio_id=None,
            symbol=symbol,
            event_type=EVENT_THESIS_EVIDENCE_CHANGED,
            event_category="thesis",
            severity="info",
            materiality="info",
            occurred_at=occurred_at,
            dedupe_key=dedupe,
            title=f"{symbol}: Tez kanıtı değişti",
            summary=change.statement,
            evidence_type="investment_thesis_snapshot",
            evidence_reference=str(current_row.get("id") or ""),
            event_payload={"change_code": change.code},
        )
        drafts.append(apply_materiality_to_draft(draft))

    return tuple(drafts)


def detect_research_status_event(
    *,
    symbol: str,
    previous_status: Optional[str],
    current_status: str,
    candidate_id: Optional[str] = None,
) -> Tuple[MonitorEventDraft, ...]:
    if not previous_status or previous_status == current_status:
        return ()
    occurred_at = _now_iso()
    dedupe = build_dedupe_key("research_status", symbol, previous_status, current_status, candidate_id)
    draft = MonitorEventDraft(
        user_id=None,
        portfolio_id=None,
        symbol=symbol,
        event_type=EVENT_RESEARCH_STATUS_CHANGED,
        event_category="research",
        severity="info",
        materiality="low",
        occurred_at=occurred_at,
        dedupe_key=dedupe,
        title=f"{symbol}: Araştırma durumu değişti",
        summary=f"Araştırma durumu {previous_status} → {current_status}.",
        evidence_type="investment_candidate",
        evidence_reference=candidate_id or symbol,
        previous_value=previous_status,
        current_value=current_status,
        event_payload={"research_status": current_status},
    )
    return (apply_materiality_to_draft(draft),)


def detect_invalidation_signal(
    *,
    symbol: str,
    journal_condition: str,
    event_summary: str,
    event_reference: str,
) -> Optional[MonitorEventDraft]:
    condition = str(journal_condition or "").strip().lower()
    summary = str(event_summary or "").strip().lower()
    if not condition or not summary:
        return None
    tokens = [token for token in condition.split() if len(token) > 4]
    if not any(token in summary for token in tokens):
        return None
    dedupe = build_dedupe_key("invalidation_signal", symbol, event_reference, journal_condition[:40])
    return MonitorEventDraft(
        user_id=None,
        portfolio_id=None,
        symbol=symbol,
        event_type=EVENT_POSSIBLE_INVALIDATION_SIGNAL,
        event_category="thesis",
        severity="watch",
        materiality="medium",
        occurred_at=_now_iso(),
        dedupe_key=dedupe,
        title=f"{symbol}: Olası geçersizleşme sinyali",
        summary=(
            "Bu değişiklik kayıtlı geçersizleşme koşulunuzla potansiyel olarak "
            "ilişkili olabilir; otomatik tez geçersizliği iddiası yoktur."
        ),
        evidence_type="decision_journal",
        evidence_reference=event_reference,
        event_payload={
            "journal_condition": journal_condition,
            "matched_event_summary": event_summary,
        },
    )
