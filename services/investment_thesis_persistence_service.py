from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

from repositories.investment_thesis_repository import InvestmentThesisRepository
from services.investment_thesis_contract import InvestmentThesisView, THESIS_VERSION


@dataclass(frozen=True)
class SaveInvestmentThesisResult:
    saved: bool
    skipped_duplicate: bool = False
    persistence_failed: bool = False
    row: Optional[Dict[str, Any]] = None
    message: str = ""


@dataclass(frozen=True)
class ThesisHistoryResult:
    history: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    available: bool = True
    message: str = ""


PERSISTENCE_HISTORY_UNAVAILABLE_MESSAGE = (
    "Yatırım tezi geçmişi şu anda yüklenemedi. Veritabanı kaydı kullanılamıyor."
)
PERSISTENCE_SAVE_FAILED_MESSAGE = (
    "Yatırım tezi kaydedilemedi. Veritabanı kaydı kullanılamıyor."
)


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def compute_semantic_identity(view: InvestmentThesisView) -> str:
    identity = {
        "symbol": _normalize_symbol(view.symbol),
        "thesis_version": view.thesis_version,
        "thesis_status": view.thesis_status,
        "valuation_context": view.valuation_context,
        "earnings_context": view.earnings_context,
        "confidence": view.confidence,
        "supporting": [
            (item.code, item.polarity, item.materiality)
            for item in view.supporting_evidence
        ],
        "weakening": [
            (item.code, item.polarity, item.materiality)
            for item in view.weakening_evidence
        ],
        "risks": [(risk.code, risk.severity) for risk in view.risks],
        "catalysts": [
            (item.catalyst_id, item.status, item.expected_date)
            for item in view.catalysts
        ],
        "invalidations": [item.code for item in view.invalidation_conditions],
        "assumptions": [(item.assumption_id, item.status) for item in view.assumptions],
        "evidence_coverage": (
            view.evidence_coverage.to_dict() if view.evidence_coverage else {}
        ),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_snapshot_payload(
    view: InvestmentThesisView,
    *,
    captured_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    timestamp = captured_at or datetime.now(timezone.utc)
    thesis_payload = view.to_dict()
    return {
        "symbol": _normalize_symbol(view.symbol),
        "captured_at": timestamp.isoformat(),
        "thesis_version": view.thesis_version or THESIS_VERSION,
        "thesis_status": view.thesis_status,
        "semantic_identity": compute_semantic_identity(view),
        "thesis_payload": thesis_payload,
        "source_version": view.thesis_version,
    }


def snapshot_from_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "captured_at": row.get("captured_at"),
        "thesis_version": row.get("thesis_version"),
        "thesis_status": row.get("thesis_status"),
        "semantic_identity": row.get("semantic_identity"),
        "thesis_payload": row.get("thesis_payload") or {},
        "source_version": row.get("source_version"),
    }


def save_investment_thesis_snapshot(
    repo: InvestmentThesisRepository,
    view: InvestmentThesisView,
    *,
    skip_if_identical: bool = True,
) -> SaveInvestmentThesisResult:
    payload = build_snapshot_payload(view)
    try:
        if skip_if_identical:
            latest = repo.get_latest(payload["symbol"])
            if (
                latest is not None
                and latest.get("semantic_identity") == payload["semantic_identity"]
            ):
                return SaveInvestmentThesisResult(
                    saved=False,
                    skipped_duplicate=True,
                    row=latest,
                    message="Bu yatırım tezi zaten kayıtlı; tekrar eklenmedi.",
                )
        row = repo.append_snapshot(payload)
    except Exception:
        return SaveInvestmentThesisResult(
            saved=False,
            persistence_failed=True,
            message=PERSISTENCE_SAVE_FAILED_MESSAGE,
        )
    return SaveInvestmentThesisResult(
        saved=True,
        row=row,
        message="Yatırım tezi kaydedildi.",
    )


def fetch_investment_thesis_history(
    repo: InvestmentThesisRepository,
    symbol: str,
    *,
    limit: int = 10,
) -> ThesisHistoryResult:
    try:
        rows = repo.get_recent_history(symbol, limit=limit)
    except Exception:
        return ThesisHistoryResult(
            history=(),
            available=False,
            message=PERSISTENCE_HISTORY_UNAVAILABLE_MESSAGE,
        )
    return ThesisHistoryResult(
        history=tuple(snapshot_from_row(row) for row in rows),
        available=True,
    )
