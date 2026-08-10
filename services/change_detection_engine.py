from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SEVERITY_WEIGHTS = {
    "HIGH": 30,
    "MEDIUM": 15,
    "LOW": 5,
}

CONFIDENCE_RANK = {
    "YÜKSEK": 3,
    "ORTA": 2,
    "DÜŞÜK": 1,
}

FRESHNESS_RANK = {
    "FRESH": 0,
    "AGING": 1,
    "STALE": 2,
    "UNKNOWN": 1,
}


def detect_changes(
    previous: Optional[Dict[str, Any]],
    current: Dict[str, Any],
) -> Dict[str, Any]:
    if previous is None:
        return {
            "has_meaningful_change": False,
            "change_score": 0,
            "changes": [],
            "no_previous": True,
            "comparison_source": None,
        }

    source = str(previous.get("_comparison_source") or "snapshot")
    changes: List[Dict[str, Any]] = []
    emitted: set[str] = set()

    def add_change(
        *,
        field: str,
        category: str,
        old: Any,
        new: Any,
        severity: str,
        message: str,
        delta: Any = None,
        dedupe_key: Optional[str] = None,
    ) -> None:
        key = dedupe_key or field
        if key in emitted:
            return
        emitted.add(key)
        changes.append({
            "field": field,
            "category": category,
            "old": old,
            "new": new,
            "delta": delta,
            "severity": severity,
            "message": message,
        })

    def legacy_field_allowed(field: str) -> bool:
        if source != "legacy_sparse":
            return True
        sparse_fields = previous.get("_sparse_fields") or []
        return field in sparse_fields

    prev_excluded = bool(previous.get("excluded"))
    curr_excluded = bool(current.get("excluded"))
    if prev_excluded != curr_excluded and _field_available(previous, "excluded", source):
        add_change(
            field="excluded",
            category="STATUS",
            old=prev_excluded,
            new=curr_excluded,
            severity="HIGH",
            message=(
                "Menkul kıymet elendi"
                if curr_excluded
                else "Menkul kıymet yeniden analiz kapsamına alındı"
            ),
        )

    if legacy_field_allowed("decision_label"):
        prev_decision = previous.get("decision_label")
        curr_decision = current.get("decision_label")
        if (
            source != "legacy_sparse"
            and prev_decision != curr_decision
            and (prev_decision or curr_decision)
        ):
            add_change(
                field="decision_label",
                category="DECISION",
                old=prev_decision,
                new=curr_decision,
                severity="HIGH",
                message=f"{prev_decision or '—'} → {curr_decision or '—'}",
            )

    _detect_freshness_changes(previous, current, source, add_change)
    _detect_score_confidence_change(previous, current, source, add_change)
    _detect_status_change(previous, current, source, add_change)
    _detect_pe_changes(previous, current, source, add_change, emitted)
    _detect_numeric_changes(previous, current, source, add_change, emitted)

    if source == "legacy_sparse":
        _detect_legacy_completeness_change(previous, current, add_change, emitted)

    change_score = min(
        100,
        sum(SEVERITY_WEIGHTS[item["severity"]] for item in changes),
    )
    has_meaningful_change = bool(changes) and (
        change_score >= 10
        or any(item["severity"] == "HIGH" for item in changes)
    )

    return {
        "has_meaningful_change": has_meaningful_change,
        "change_score": change_score,
        "changes": changes,
        "no_previous": False,
        "comparison_source": source,
    }


def rank_changes(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(item: Dict[str, Any]) -> Tuple[float, int, str]:
        change = item.get("change") or {}
        high_count = sum(
            1
            for event in change.get("changes") or []
            if event.get("severity") == "HIGH"
        )
        return (
            -float(change.get("change_score") or 0),
            -high_count,
            str(item.get("symbol") or ""),
        )

    return sorted(items, key=sort_key)


def _field_available(
    snapshot: Dict[str, Any],
    field: str,
    source: str,
) -> bool:
    if source != "legacy_sparse":
        return field in snapshot
    sparse_fields = snapshot.get("_sparse_fields") or []
    return field in sparse_fields


def _detect_freshness_changes(
    previous: Dict[str, Any],
    current: Dict[str, Any],
    source: str,
    add_change,
) -> None:
    if source == "legacy_sparse":
        return

    prev_status = previous.get("freshness_status")
    curr_status = current.get("freshness_status")
    if not prev_status or not curr_status or prev_status == curr_status:
        return

    prev_rank = FRESHNESS_RANK.get(prev_status, 0)
    curr_rank = FRESHNESS_RANK.get(curr_status, 0)
    if curr_rank <= prev_rank:
        return

    if prev_status == "FRESH" and curr_status == "AGING":
        severity = "MEDIUM"
    elif curr_status == "STALE":
        severity = "HIGH"
    else:
        severity = "MEDIUM"

    add_change(
        field="freshness_status",
        category="FRESHNESS",
        old=prev_status,
        new=curr_status,
        severity=severity,
        message=f"Freshness {prev_status} → {curr_status}",
    )


def _detect_score_confidence_change(
    previous: Dict[str, Any],
    current: Dict[str, Any],
    source: str,
    add_change,
) -> None:
    if source == "legacy_sparse":
        return

    prev_conf = previous.get("score_confidence")
    curr_conf = current.get("score_confidence")
    if not prev_conf or not curr_conf or prev_conf == curr_conf:
        return

    prev_rank = CONFIDENCE_RANK.get(prev_conf, 0)
    curr_rank = CONFIDENCE_RANK.get(curr_conf, 0)
    if curr_rank >= prev_rank:
        return

    severity = "HIGH" if prev_conf == "YÜKSEK" and curr_conf == "DÜŞÜK" else "MEDIUM"
    add_change(
        field="score_confidence",
        category="CONFIDENCE",
        old=prev_conf,
        new=curr_conf,
        severity=severity,
        message=f"Skor güveni {prev_conf} → {curr_conf}",
    )


def _detect_status_change(
    previous: Dict[str, Any],
    current: Dict[str, Any],
    source: str,
    add_change,
) -> None:
    if not _field_available(previous, "status", source):
        return
    if source == "legacy_sparse":
        return

    prev_status = previous.get("status")
    curr_status = current.get("status")
    if not prev_status or not curr_status or prev_status == curr_status:
        return

    meaningful_pairs = {
        ("KISMİ VERİ", "YETERLİ VERİ"),
        ("KISMİ VERİ", "TAM VERİ"),
        ("YETERLİ VERİ", "TAM VERİ"),
        ("ELENDİ", "TAM VERİ"),
        ("ELENDİ", "YETERLİ VERİ"),
        ("ELENDİ", "KISMİ VERİ"),
    }
    if (prev_status, curr_status) not in meaningful_pairs:
        return

    severity = "HIGH" if "TAM VERİ" in (prev_status, curr_status) else "MEDIUM"
    if source == "legacy_sparse":
        message = f"Veri durumu {prev_status} → {curr_status}"
    else:
        message = f"Veri durumu {prev_status} → {curr_status}"

    add_change(
        field="status",
        category="DATA_STATUS",
        old=prev_status,
        new=curr_status,
        severity=severity,
        message=message,
    )


def _detect_pe_changes(
    previous: Dict[str, Any],
    current: Dict[str, Any],
    source: str,
    add_change,
    emitted: set[str],
) -> None:
    if source == "legacy_sparse":
        return

    prev_pe = previous.get("pe_ratio")
    curr_pe = current.get("pe_ratio")
    prev_source = previous.get("pe_source")
    curr_source = current.get("pe_source")

    if prev_pe is None and curr_pe is not None and curr_source in {"quote", "ratios_ttm"}:
        add_change(
            field="pe_ratio",
            category="AVAILABILITY",
            old=None,
            new=curr_pe,
            severity="HIGH",
            message=f"PE verisi artık mevcut: {curr_pe:.1f}",
            dedupe_key="pe_availability",
        )
        return

    if prev_pe is not None and curr_pe is None:
        if curr_source == "unavailable":
            add_change(
                field="pe_source",
                category="AVAILABILITY",
                old=prev_source,
                new=curr_source,
                severity="MEDIUM",
                message="PE verisi geçici olarak erişilemedi",
                dedupe_key="pe_availability",
            )
            return
        if curr_source == "missing":
            add_change(
                field="pe_source",
                category="AVAILABILITY",
                old=prev_source,
                new=curr_source,
                severity="MEDIUM",
                message="PE verisi artık mevcut değil",
                dedupe_key="pe_availability",
            )
            return

    if (
        prev_source in {"unavailable", "missing", None}
        and curr_source in {"quote", "ratios_ttm"}
        and curr_pe is not None
    ):
        add_change(
            field="pe_source",
            category="AVAILABILITY",
            old=prev_source,
            new=curr_source,
            severity="HIGH",
            message=(
                f"PE verisi yeniden erişilebilir: {curr_pe:.1f}"
                if curr_pe is not None
                else "PE verisi yeniden erişilebilir"
            ),
            dedupe_key="pe_availability",
        )
        return

    if prev_pe is None or curr_pe is None:
        return
    if "pe_availability" in emitted:
        return

    if prev_pe == 0:
        return

    relative = abs(curr_pe - prev_pe) / abs(prev_pe)
    if relative >= 0.15:
        delta = round(curr_pe - prev_pe, 1)
        add_change(
            field="pe_ratio",
            category="VALUATION",
            old=prev_pe,
            new=curr_pe,
            delta=delta,
            severity="MEDIUM",
            message=f"PE {prev_pe:.1f} → {curr_pe:.1f} ({delta:+.1f})",
        )


def _detect_numeric_changes(
    previous: Dict[str, Any],
    current: Dict[str, Any],
    source: str,
    add_change,
    emitted: set[str],
) -> None:
    numeric_rules = [
        ("nabi_score", "SCORE", 3, "NABI Skoru"),
        ("opportunity_score", "SCORE", 5, "Fırsat Potansiyeli"),
        ("conviction_score", "SCORE", 5, "Araştırma Güveni"),
        ("research_confidence", "CONFIDENCE", 8, "Veri Güveni"),
        ("data_completeness", "COMPLETENESS", 8, "Veri tamlığı"),
        ("roic", "QUALITY", 5, "ROIC"),
        ("revenue_growth_1y", "GROWTH", 5, "Gelir büyümesi"),
        ("revenue_cagr_3y", "GROWTH", 5, "Gelir CAGR"),
        ("free_cash_flow_margin", "QUALITY", 5, "FCF marjı"),
    ]

    for field, category, threshold, label in numeric_rules:
        if not _field_available(previous, field, source):
            continue
        if field == "data_completeness" and source == "legacy_sparse":
            continue

        prev_val = _as_float(previous.get(field))
        curr_val = _as_float(current.get(field))
        if prev_val is None or curr_val is None:
            continue

        delta = round(curr_val - prev_val, 1)
        if abs(delta) < threshold:
            continue

        if field == "data_completeness":
            message = f"Veri tamlığı %{prev_val:.0f} → %{curr_val:.0f}"
        elif field == "research_confidence":
            message = f"{label} {prev_val:.1f} → {curr_val:.1f} ({delta:+.1f})"
        else:
            message = f"{label} {prev_val:.1f} → {curr_val:.1f} ({delta:+.1f})"

        severity = "MEDIUM" if field in {"nabi_score", "opportunity_score", "conviction_score"} else "LOW"
        if field == "research_confidence" and abs(delta) >= 15:
            severity = "MEDIUM"

        add_change(
            field=field,
            category=category,
            old=prev_val,
            new=curr_val,
            delta=delta,
            severity=severity,
            message=message,
        )


def _detect_legacy_completeness_change(
    previous: Dict[str, Any],
    current: Dict[str, Any],
    add_change,
    emitted: set[str],
) -> None:
    if "legacy_completeness" in emitted:
        return

    prev_val = _as_float(previous.get("data_completeness"))
    curr_val = _as_float(current.get("data_completeness"))
    if prev_val is None or curr_val is None:
        return
    if abs(curr_val - prev_val) < 8:
        return

    add_change(
        field="data_completeness",
        category="COMPLETENESS",
        old=prev_val,
        new=curr_val,
        delta=round(curr_val - prev_val, 1),
        severity="MEDIUM",
        message=(
            f"Veri kapsamı değişti: %{prev_val:.0f} → %{curr_val:.0f}"
        ),
        dedupe_key="legacy_completeness",
    )


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
