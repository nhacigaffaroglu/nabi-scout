from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from repositories.participation_assessment_repository import (
    ParticipationAssessmentRepository,
)
from services.company_report_participation_service import CompanyReportParticipationView
from services.participation_assessment_service import ParticipationAssessmentResult
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN


@dataclass(frozen=True)
class SaveParticipationAssessmentResult:
    saved: bool
    skipped_duplicate: bool = False
    row: Optional[Dict[str, Any]] = None
    message: str = ""


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _rule_outcomes(rules: Any) -> Tuple[Tuple[str, str], ...]:
    if not rules:
        return ()
    return tuple((rule.rule_id, rule.outcome) for rule in rules)


def compute_semantic_identity(result: ParticipationAssessmentResult) -> str:
    assessment = result.participation_assessment
    financial = result.financial_screen_result
    business = result.business_screen_result
    identity = {
        "symbol": _normalize_symbol(result.symbol),
        "methodology_id": assessment.methodology_id or result.methodology_id,
        "methodology_version": (
            assessment.methodology_version or result.resolved_methodology_version
        ),
        "status": assessment.status,
        "source": assessment.source,
        "confidence": assessment.confidence,
        "methodology_completeness": assessment.methodology_completeness,
        "data_completeness_pct": assessment.data_completeness_pct,
        "holdings_coverage_pct": assessment.holdings_coverage_pct,
        "freshness_label": assessment.freshness_label,
        "financial_overall_outcome": (
            financial.overall_outcome if financial is not None else None
        ),
        "business_overall_outcome": (
            business.overall_outcome if business is not None else None
        ),
        "missing_capabilities": sorted(result.missing_capabilities),
        "financial_rule_outcomes": _rule_outcomes(
            financial.rule_results if financial is not None else None
        ),
        "business_rule_outcomes": _rule_outcomes(
            business.rule_results if business is not None else None
        ),
        "provider_status": dict(result.provider_status),
        "sec_available": result.sec_available,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_snapshot_payload(
    result: ParticipationAssessmentResult,
    *,
    assessed_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    assessment = result.participation_assessment
    financial = result.financial_screen_result
    business = result.business_screen_result
    timestamp = assessed_at or datetime.now(timezone.utc)
    audit_payload = result.to_dict()
    audit_payload.pop("participation_score", None)

    return {
        "symbol": _normalize_symbol(result.symbol),
        "assessed_at": timestamp.isoformat(),
        "methodology_id": assessment.methodology_id or result.methodology_id,
        "methodology_version": (
            assessment.methodology_version or result.resolved_methodology_version
        ),
        "status": assessment.status,
        "source": assessment.source,
        "confidence": assessment.confidence,
        "methodology_completeness": assessment.methodology_completeness,
        "data_completeness_pct": assessment.data_completeness_pct,
        "holdings_coverage_pct": assessment.holdings_coverage_pct,
        "freshness_label": assessment.freshness_label,
        "financial_overall_outcome": (
            financial.overall_outcome if financial is not None else None
        ),
        "business_overall_outcome": (
            business.overall_outcome if business is not None else None
        ),
        "provider_status": dict(result.provider_status),
        "sec_available": result.sec_available,
        "warnings": list(result.warnings),
        "errors": list(result.errors),
        "missing_capabilities": list(result.missing_capabilities),
        "source_evidence": dict(result.source_evidence),
        "assessment_payload": audit_payload,
        "semantic_identity": compute_semantic_identity(result),
    }


def snapshot_from_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "assessed_at": row.get("assessed_at"),
        "methodology_id": row.get("methodology_id"),
        "methodology_version": row.get("methodology_version"),
        "status": row.get("status"),
        "source": row.get("source"),
        "confidence": row.get("confidence"),
        "methodology_completeness": row.get("methodology_completeness"),
        "data_completeness_pct": row.get("data_completeness_pct"),
        "holdings_coverage_pct": row.get("holdings_coverage_pct"),
        "freshness_label": row.get("freshness_label"),
        "financial_overall_outcome": row.get("financial_overall_outcome"),
        "business_overall_outcome": row.get("business_overall_outcome"),
        "provider_status": row.get("provider_status") or {},
        "sec_available": row.get("sec_available"),
        "warnings": row.get("warnings") or [],
        "errors": row.get("errors") or [],
        "missing_capabilities": row.get("missing_capabilities") or [],
        "source_evidence": row.get("source_evidence") or {},
        "semantic_identity": row.get("semantic_identity"),
        "assessment_payload": row.get("assessment_payload") or {},
    }


def save_participation_assessment_snapshot(
    repo: ParticipationAssessmentRepository,
    view: CompanyReportParticipationView,
    *,
    skip_if_identical: bool = True,
) -> SaveParticipationAssessmentResult:
    if not view.available or view.result is None:
        return SaveParticipationAssessmentResult(
            saved=False,
            message="Kaydedilecek katılım incelemesi sonucu yok.",
        )

    payload = build_snapshot_payload(view.result)
    if skip_if_identical:
        latest = repo.get_latest(payload["symbol"])
        if (
            latest is not None
            and latest.get("semantic_identity") == payload["semantic_identity"]
        ):
            return SaveParticipationAssessmentResult(
                saved=False,
                skipped_duplicate=True,
                row=latest,
                message="Bu katılım incelemesi zaten kayıtlı; tekrar eklenmedi.",
            )

    row = repo.append_snapshot(payload)
    return SaveParticipationAssessmentResult(
        saved=True,
        row=row,
        message="Katılım incelemesi kaydedildi.",
    )


def fetch_latest_participation_assessment(
    repo: ParticipationAssessmentRepository,
    symbol: str,
) -> Optional[Dict[str, Any]]:
    row = repo.get_latest(symbol)
    return snapshot_from_row(row) if row is not None else None


def fetch_participation_assessment_history(
    repo: ParticipationAssessmentRepository,
    symbol: str,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    return [
        snapshot_from_row(row)
        for row in repo.get_recent_history(symbol, limit=limit)
    ]


def saved_snapshot_is_final_uygun(snapshot: Mapping[str, Any]) -> bool:
    return snapshot.get("status") == PARTICIPATION_STATUS_UYGUN
