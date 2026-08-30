"""Canonical Turkish fund snapshot payloads. Compute only. No writes.

Reuses security_intelligence_snapshots for FI and
participation_assessment_snapshots for Participation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.fund_decision_readiness import TURKIYE_FUND_8E_INSTRUMENT, TURKIYE_FUND_8E_MARKET
from services.fund_product_contract import (
    FUND_EVAL_ENGINE_VERSION,
    FUND_EVAL_FACTS_VERSION,
    IDENTITY_RESOLVED,
    LAYER_CASH_LIKE,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
    METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION,
    OfficialFundEconomicClassification,
    TurkiyeFundIdentity,
    TurkiyeFundParticipationVerdict,
    FundIntelligenceEvaluation,
)
from services.official_turkiye_fund_participation import load_participation_bundle
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN
from services.portfolio_security_decision_contract import (
    DECISION_INSUFFICIENT_DATA,
    DECISION_WATCH,
    ENGINE_VERSION as EIGHT_E_ENGINE_VERSION,
    PortfolioSecurityDecision,
)
from services.security_intelligence_snapshot_service import as_of_key
from services.turkiye_fund_refresh_contract import (
    LAYER_ECONOMIC_EXPOSURE,
    LAYER_EIGHT_E,
    LAYER_FUND_INTELLIGENCE,
    LAYER_IDENTITY,
    LAYER_PARTICIPATION,
    TABLE_PARTICIPATION_SNAPSHOTS,
    TABLE_SI_SNAPSHOTS,
)


def _now_iso(calculated_at: Optional[str] = None) -> str:
    return calculated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def semantic_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_as_of_bundle(
    *,
    tefas_price: Optional[str],
    kap_pdr: Optional[str],
    kap_mandate: Optional[str],
    kap_izahname: Optional[str],
) -> dict[str, Optional[str]]:
    return {
        "tefas_price": tefas_price,
        "kap_pdr": kap_pdr,
        "kap_mandate": kap_mandate,
        "kap_izahname": kap_izahname,
    }


def izahname_date_for(fund_code: str) -> Optional[str]:
    funds = dict(load_participation_bundle().get("funds") or {})
    row = dict(funds.get(fund_code) or {})
    return str(row.get("izahname_date") or "") or None


@dataclass(frozen=True)
class TurkiyeFundLayerSnapshot:
    layer: str
    fund_code: str
    instrument: str
    market: str
    target_table: Optional[str]
    idempotency_key: str
    source_as_of: dict[str, Optional[str]]
    calculated_at: str
    methodology_version: Optional[str]
    publishable: bool
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "fund_code": self.fund_code,
            "instrument": self.instrument,
            "market": self.market,
            "target_table": self.target_table,
            "idempotency_key": self.idempotency_key,
            "source_as_of": dict(self.source_as_of),
            "calculated_at": self.calculated_at,
            "methodology_version": self.methodology_version,
            "publishable": self.publishable,
            "payload": dict(self.payload),
        }


def _envelope(
    *,
    layer: str,
    fund_code: str,
    target_table: Optional[str],
    methodology_version: Optional[str],
    source_as_of: Mapping[str, Optional[str]],
    calculated_at: str,
    publishable: bool,
    semantic: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> TurkiyeFundLayerSnapshot:
    key_material = {
        "fund_code": fund_code,
        "layer": layer,
        "methodology_version": methodology_version,
        "source_as_of": dict(source_as_of),
        "semantic": dict(semantic),
    }
    return TurkiyeFundLayerSnapshot(
        layer=layer,
        fund_code=fund_code,
        instrument=TURKIYE_FUND_8E_INSTRUMENT,
        market=TURKIYE_FUND_8E_MARKET,
        target_table=target_table,
        idempotency_key=semantic_hash(key_material),
        source_as_of=dict(source_as_of),
        calculated_at=calculated_at,
        methodology_version=methodology_version,
        publishable=publishable,
        payload=dict(payload),
    )


def identity_snapshot(
    identity: TurkiyeFundIdentity,
    *,
    source_as_of: Mapping[str, Optional[str]],
    calculated_at: Optional[str] = None,
) -> TurkiyeFundLayerSnapshot:
    stamp = _now_iso(calculated_at)
    semantic = {
        "fund_code": identity.fund_code,
        "official_name": identity.official_name,
        "identity_status": identity.identity_status,
        "isin": identity.isin,
        "currency": identity.currency,
        "founder": identity.founder,
    }
    payload = {
        **semantic,
        "instrument": TURKIYE_FUND_8E_INSTRUMENT,
        "market": TURKIYE_FUND_8E_MARKET,
        "tefas_source": identity.tefas_source,
        "tefas_source_url": identity.tefas_source_url,
        "kap_source": identity.kap_source,
        "kap_source_url": identity.kap_source_url,
        "source_as_of": dict(source_as_of),
        "calculated_at": stamp,
    }
    return _envelope(
        layer=LAYER_IDENTITY,
        fund_code=identity.fund_code,
        target_table=None,
        methodology_version=None,
        source_as_of=source_as_of,
        calculated_at=stamp,
        publishable=identity.identity_status == IDENTITY_RESOLVED,
        semantic=semantic,
        payload=payload,
    )


def participation_snapshot(
    verdict: TurkiyeFundParticipationVerdict,
    *,
    source_as_of: Mapping[str, Optional[str]],
    calculated_at: Optional[str] = None,
) -> TurkiyeFundLayerSnapshot:
    stamp = _now_iso(calculated_at)
    semantic = {
        "fund_code": verdict.fund_code,
        "methodology_id": verdict.methodology_id,
        "methodology_version": verdict.methodology_version,
        "participation_status": verdict.participation_status,
        "research_allowed": verdict.research_allowed,
        "mandate_state": verdict.mandate_state,
        "governance_state": verdict.governance_state,
        "holdings_state": verdict.holdings_state,
        "freshness": verdict.freshness,
        "blockers": list(verdict.blockers),
    }
    payload = {
        "symbol": verdict.fund_code,
        "status": verdict.participation_status,
        "research_allowed": verdict.research_allowed,
        "methodology_id": METHODOLOGY_TURKIYE_FUND_PARTICIPATION,
        "methodology_version": METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION,
        "source": "kap_izahname_pdr",
        "confidence": "HIGH" if verdict.governance_state == "CONFIRMED" else "LOW",
        "freshness_label": verdict.freshness,
        "source_evidence": {
            "mandate_state": verdict.mandate_state,
            "governance_state": verdict.governance_state,
            "icazet_present": verdict.icazet_present,
            "holdings_state": verdict.holdings_state,
            "source_as_of": dict(source_as_of),
        },
        "assessment_payload": {
            "participation_status": verdict.participation_status,
            "research_allowed": verdict.research_allowed,
            "blockers": list(verdict.blockers),
        },
        "semantic_identity": semantic_hash(semantic),
        "calculated_at": stamp,
        "assessed_at": stamp,
    }
    return _envelope(
        layer=LAYER_PARTICIPATION,
        fund_code=verdict.fund_code,
        target_table=TABLE_PARTICIPATION_SNAPSHOTS,
        methodology_version=METHODOLOGY_TURKIYE_FUND_PARTICIPATION_VERSION,
        source_as_of=source_as_of,
        calculated_at=stamp,
        publishable=verdict.participation_status == PARTICIPATION_STATUS_UYGUN,
        semantic=semantic,
        payload=payload,
    )


def fund_intelligence_snapshot(
    view: FundIntelligenceEvaluation,
    *,
    source_as_of: Mapping[str, Optional[str]],
    calculated_at: Optional[str] = None,
    exposure: Optional[OfficialFundEconomicClassification] = None,
    research_allowed: bool = False,
    participation_status: Optional[str] = None,
) -> TurkiyeFundLayerSnapshot:
    stamp = _now_iso(calculated_at)
    generic = view.generic_intelligence()
    scores = {row.name: row.score for row in view.dimensions if row.score is not None}
    semantic = {
        "symbol": view.symbol,
        "as_of": view.as_of,
        "as_of_key": as_of_key(view.as_of),
        "facts_version": view.facts_version or FUND_EVAL_FACTS_VERSION,
        "engine_version": view.engine_version or FUND_EVAL_ENGINE_VERSION,
        "overall_score": view.score,
        "investment_state": view.state,
        "completeness": view.completeness,
        "confidence": view.confidence,
        "participation_status": participation_status,
        "research_allowed": research_allowed,
    }
    exposure_payload = None
    if exposure is not None:
        exposure_payload = {
            "primary_exposure": exposure.primary_exposure,
            "geography": exposure.geography,
            "confidence": exposure.confidence,
            "lookthrough_weights": [list(item) for item in exposure.lookthrough_weights],
        }
    payload = {
        "symbol": view.symbol,
        "as_of": view.as_of,
        "as_of_key": as_of_key(view.as_of),
        "facts_version": view.facts_version or FUND_EVAL_FACTS_VERSION,
        "engine_version": view.engine_version or FUND_EVAL_ENGINE_VERSION,
        "overall_score": view.score,
        "overall_status": view.state,
        "overall_confidence": view.confidence,
        "investment_state": view.state,
        "participation_status": participation_status,
        "research_allowed": research_allowed,
        "dimension_scores": scores,
        "dimension_statuses": view.evidence_map(),
        "data_quality": {
            "si_data_quality": generic.get("si_data_quality"),
            "completeness": view.completeness,
            "instrument": TURKIYE_FUND_8E_INSTRUMENT,
            "market": TURKIYE_FUND_8E_MARKET,
            "economic_exposure": exposure_payload,
        },
        "strengths": [],
        "weaknesses": [],
        "risk_flags": [],
        "reason_codes": list(view.missing_evidence),
        "change_flags": [],
        "source_as_of": dict(source_as_of),
        "calculated_at": stamp,
    }
    return _envelope(
        layer=LAYER_FUND_INTELLIGENCE,
        fund_code=view.symbol,
        target_table=TABLE_SI_SNAPSHOTS,
        methodology_version=view.engine_version or FUND_EVAL_ENGINE_VERSION,
        source_as_of=source_as_of,
        calculated_at=stamp,
        publishable=bool(view.publishable),
        semantic=semantic,
        payload=payload,
    )


def economic_exposure_snapshot(
    classification: Optional[OfficialFundEconomicClassification],
    *,
    fund_code: str,
    source_as_of: Mapping[str, Optional[str]],
    calculated_at: Optional[str] = None,
) -> TurkiyeFundLayerSnapshot:
    stamp = _now_iso(calculated_at)
    if classification is None:
        semantic = {"fund_code": fund_code, "ready": False}
        payload = {
            "fund_code": fund_code,
            "primary_exposure": None,
            "ready": False,
            "source_as_of": dict(source_as_of),
            "calculated_at": stamp,
        }
        return _envelope(
            layer=LAYER_ECONOMIC_EXPOSURE,
            fund_code=fund_code,
            target_table=TABLE_SI_SNAPSHOTS,
            methodology_version=None,
            source_as_of=source_as_of,
            calculated_at=stamp,
            publishable=False,
            semantic=semantic,
            payload=payload,
        )
    if classification.primary_exposure == "cash":
        raise ValueError("ais_cash_firewall: portfolio CASH is not a valid AIS exposure")
    semantic = {
        "fund_code": classification.symbol,
        "primary_exposure": classification.primary_exposure,
        "geography": classification.geography,
        "confidence": classification.confidence,
        "lookthrough_weights": [list(item) for item in classification.lookthrough_weights],
        "subgroup_weights": [list(item) for item in classification.subgroup_weights],
        "ready": classification.ready,
    }
    payload = {
        "fund_code": classification.symbol,
        "instrument": classification.instrument,
        "primary_exposure": classification.primary_exposure,
        "geography": classification.geography,
        "confidence": classification.confidence,
        "lookthrough_weights": [list(item) for item in classification.lookthrough_weights],
        "subgroup_weights": [list(item) for item in classification.subgroup_weights],
        "source": classification.source,
        "source_url": classification.source_url,
        "as_of": classification.as_of,
        "evidence_basis": list(classification.evidence_basis),
        "ready": classification.ready,
        "limitations": list(classification.limitations),
        "source_as_of": dict(source_as_of),
        "calculated_at": stamp,
    }
    return _envelope(
        layer=LAYER_ECONOMIC_EXPOSURE,
        fund_code=classification.symbol,
        target_table=TABLE_SI_SNAPSHOTS,
        methodology_version=None,
        source_as_of=source_as_of,
        calculated_at=stamp,
        publishable=bool(classification.ready),
        semantic=semantic,
        payload=payload,
    )


def eight_e_snapshot(
    decision: PortfolioSecurityDecision,
    *,
    source_as_of: Mapping[str, Optional[str]],
    calculated_at: Optional[str] = None,
    upstream_ready: bool = False,
) -> TurkiyeFundLayerSnapshot:
    stamp = _now_iso(calculated_at)
    semantic = {
        "symbol": decision.symbol,
        "decision": decision.decision,
        "increase_allowed": decision.exposure_increase_allowed,
        "blocking_reasons": list(decision.blocking_reasons),
        "engine_version": decision.engine_version or EIGHT_E_ENGINE_VERSION,
        "participation_status": decision.participation_status,
        "research_allowed": decision.research_allowed,
        "security_intelligence_state": decision.security_intelligence_state,
        "security_intelligence_score": decision.security_intelligence_score,
    }
    payload = {
        **decision.to_dict(),
        "instrument": TURKIYE_FUND_8E_INSTRUMENT,
        "market": TURKIYE_FUND_8E_MARKET,
        "increase_allowed": decision.exposure_increase_allowed,
        "source_as_of": dict(source_as_of),
        "calculated_at": stamp,
    }
    publishable = bool(upstream_ready) and decision.decision != DECISION_INSUFFICIENT_DATA
    return _envelope(
        layer=LAYER_EIGHT_E,
        fund_code=decision.symbol,
        target_table=None,
        methodology_version=decision.engine_version or EIGHT_E_ENGINE_VERSION,
        source_as_of=source_as_of,
        calculated_at=stamp,
        publishable=publishable,
        semantic=semantic,
        payload=payload,
    )


def blocked_snapshot(
    layer: str,
    fund_code: str,
    *,
    source_as_of: Mapping[str, Optional[str]],
    calculated_at: Optional[str] = None,
    reason: str,
    target_table: Optional[str] = None,
    methodology_version: Optional[str] = None,
) -> TurkiyeFundLayerSnapshot:
    stamp = _now_iso(calculated_at)
    semantic = {"fund_code": fund_code, "ready": False, "reason": reason}
    payload = {
        "fund_code": fund_code,
        "instrument": TURKIYE_FUND_8E_INSTRUMENT,
        "market": TURKIYE_FUND_8E_MARKET,
        "ready": False,
        "reason": reason,
        "source_as_of": dict(source_as_of),
        "calculated_at": stamp,
    }
    return _envelope(
        layer=layer,
        fund_code=fund_code,
        target_table=target_table,
        methodology_version=methodology_version,
        source_as_of=source_as_of,
        calculated_at=stamp,
        publishable=False,
        semantic=semantic,
        payload=payload,
    )


def assert_ais_not_portfolio_cash(snapshot: TurkiyeFundLayerSnapshot) -> None:
    primary = snapshot.payload.get("primary_exposure")
    nested = ((snapshot.payload.get("data_quality") or {}).get("economic_exposure") or {}).get(
        "primary_exposure"
    )
    for value in (primary, nested):
        if value == "cash":
            raise ValueError("ais_cash_firewall")
        if value is not None and value != LAYER_CASH_LIKE and snapshot.fund_code == "AIS":
            raise ValueError("ais_cash_firewall")


