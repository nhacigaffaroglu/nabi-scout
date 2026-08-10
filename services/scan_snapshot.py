from __future__ import annotations

from typing import Any, Dict, Optional


SNAPSHOT_FIELDS = (
    "symbol",
    "status",
    "excluded",
    "security_type",
    "issuer_category",
    "nabi_score",
    "decision_label",
    "opportunity_score",
    "conviction_score",
    "research_confidence",
    "score_confidence",
    "data_completeness",
    "freshness_status",
    "freshness_label",
    "period_age_days",
    "financial_period_end",
    "pe_ratio",
    "pe_source",
    "roic",
    "revenue_growth_1y",
    "revenue_cagr_3y",
    "free_cash_flow_margin",
    "financial_taxonomy",
    "financial_currency",
    "fmp_source_status",
    "endpoint_status",
)


def normalize_universe_name(universe_name: Optional[str]) -> str:
    if not universe_name:
        return ""
    name = universe_name.strip()
    marker = " ["
    idx = name.rfind(marker)
    if idx > 0 and name.endswith("]"):
        return name[:idx].strip()
    return name


def _issuer_category(
    candidate: Dict[str, Any],
    *,
    excluded: bool,
) -> str:
    if candidate.get("issuer_category"):
        return str(candidate["issuer_category"])
    security_type = str(candidate.get("security_type") or "").upper()
    if excluded:
        if "ETF" in security_type:
            return "FUND"
        return "SPECIAL_SECURITY"
    return "OPERATING_COMPANY"


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def build_scan_snapshot(result: Dict[str, Any]) -> Dict[str, Any]:
    candidate = result.get("candidate") or {}
    excluded = bool(result.get("excluded"))
    endpoint_status = result.get("endpoint_status") or {}

    snapshot = {
        "symbol": result.get("symbol") or candidate.get("symbol"),
        "status": result.get("status"),
        "excluded": excluded,
        "security_type": candidate.get("security_type"),
        "issuer_category": _issuer_category(candidate, excluded=excluded),
        "nabi_score": candidate.get("nabi_score"),
        "decision_label": candidate.get("decision_label"),
        "opportunity_score": candidate.get("opportunity_score"),
        "conviction_score": candidate.get("conviction_score"),
        "research_confidence": candidate.get("research_confidence"),
        "score_confidence": candidate.get("score_confidence"),
        "data_completeness": candidate.get("data_completeness"),
        "freshness_status": candidate.get("freshness_status"),
        "freshness_label": candidate.get("freshness_label"),
        "period_age_days": candidate.get("period_age_days"),
        "financial_period_end": candidate.get("financial_period_end"),
        "pe_ratio": candidate.get("pe_ratio"),
        "pe_source": candidate.get("pe_source"),
        "roic": candidate.get("roic"),
        "revenue_growth_1y": (
            candidate.get("revenue_growth_1y")
            if candidate.get("revenue_growth_1y") is not None
            else candidate.get("revenue_growth")
        ),
        "revenue_cagr_3y": candidate.get("revenue_cagr_3y"),
        "free_cash_flow_margin": candidate.get("free_cash_flow_margin"),
        "financial_taxonomy": candidate.get("financial_taxonomy"),
        "financial_currency": candidate.get("financial_currency"),
        "fmp_source_status": candidate.get("fmp_source_status"),
        "endpoint_status": endpoint_status,
        "_comparison_source": "snapshot",
    }
    return {key: _json_value(snapshot[key]) for key in SNAPSHOT_FIELDS + ("_comparison_source",)}


def snapshot_from_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    completeness = float(candidate.get("data_completeness") or 0)
    if completeness >= 85:
        status = "TAM VERİ"
    elif completeness >= 65:
        status = "YETERLİ VERİ"
    else:
        status = "KISMİ VERİ"

    return build_scan_snapshot({
        "symbol": candidate.get("symbol"),
        "excluded": False,
        "status": status,
        "endpoint_status": candidate.get("endpoint_status") or {},
        "errors": [],
        "candidate": candidate,
    })


def sparse_snapshot_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = {
        "symbol": row.get("symbol"),
        "status": row.get("status"),
        "excluded": row.get("status") == "ELENDİ",
        "nabi_score": row.get("nabi_score"),
        "data_completeness": row.get("data_completeness"),
        "endpoint_status": row.get("endpoint_status"),
        "_comparison_source": "legacy_sparse",
        "_sparse_fields": [
            "symbol",
            "status",
            "excluded",
            "data_completeness",
            "endpoint_status",
        ],
    }
    return {key: _json_value(snapshot[key]) for key in snapshot}
