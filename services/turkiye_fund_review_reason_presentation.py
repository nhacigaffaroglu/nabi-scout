"""Shared read-only presentation helpers for Türkiye fund review reasons.

FUND25-D.
This module interprets existing scanner output for diagnostics/UI only.
It does not change scanner, Participation, FI, 8E, New Money, ranking,
portfolio state, persistence, or execution behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping, Sequence

READY = "READY"
UNCLASSIFIED_REVIEW_GATE = "UNCLASSIFIED_REVIEW_GATE"

_ASSET_GROUPS = frozenset(
    {
        "CASH",
        "EQUITY",
        "FUND",
        "LEASE_CERTIFICATE",
        "OTHER",
        "PARTICIPATION_ACCOUNT",
        "REPO",
        "UNKNOWN",
        "DERIVATIVE",
        "PRECIOUS_METALS",
    }
)

_KNOWN_REASON_CODES = frozenset(
    {
        "PARTICIPATION_REVIEW",
        "FI_INSUFFICIENT_DATA",
        "FI_NOT_PUBLISHABLE",
        "HISTORY_INSUFFICIENT",
        "PDR_RECONCILIATION_FAILED",
        "PDR_WEIGHTS_UNRECONCILED",
        "PDR_PARSE_INCOMPLETE",
        "PDR_MISSING",
        "HOLDINGS_MISSING",
        "SOURCE_STALE",
        "EVIDENCE_STALE",
        "SOURCE_ERROR",
        "TEXT_LAYER_UNAVAILABLE",
        "ECONOMIC_EXPOSURE_UNKNOWN",
        "GOVERNANCE_EVIDENCE_MISSING",
        "GOVERNANCE_NOT_CONFIRMED",
        "MANDATE_UNRESOLVED",
        "NAME_ALONE_INSUFFICIENT",
        "MATERIAL_CONTRADICTION",
        "IAT_KIRA_BELOW_80",
        "IAT_OTHER_POSITIVE_WEIGHT",
        "AIS_KATILMA_OVER_50",
        "ZPE_XK_SLEEVE_BELOW_80",
        "YBF_MISSING",
        "FI_PROFILE_UNROUTED",
        "TEFAS_INACTIVE",
        "TEFAS_ACTIVE_UNPROVEN",
    }
)

_WRAPPER_REASONS = frozenset(
    {
        "PARTICIPATION_REVIEW",
        "FI_INSUFFICIENT_DATA",
        "FI_NOT_PUBLISHABLE",
    }
)

_FAMILY_BY_CODE = {
    "SOURCE_ERROR": "SOURCE_CAPTURE",
    "SOURCE_STALE": "SOURCE_CAPTURE",
    "EVIDENCE_STALE": "SOURCE_CAPTURE",
    "TEFAS_INACTIVE": "SOURCE_CAPTURE",
    "TEFAS_ACTIVE_UNPROVEN": "SOURCE_CAPTURE",
    "TEXT_LAYER_UNAVAILABLE": "SOURCE_CAPTURE",
    "PDR_MISSING": "PDR_MISSING_OR_STALE",
    "HOLDINGS_MISSING": "PDR_MISSING_OR_STALE",
    "YBF_MISSING": "PDR_MISSING_OR_STALE",
    "PDR_PARSE_INCOMPLETE": "PDR_PARSE",
    "PDR_RECONCILIATION_FAILED": "PDR_RECONCILIATION",
    "PDR_WEIGHTS_UNRECONCILED": "PDR_RECONCILIATION",
    "GOVERNANCE_EVIDENCE_MISSING": "GOVERNANCE",
    "GOVERNANCE_NOT_CONFIRMED": "GOVERNANCE",
    "MANDATE_UNRESOLVED": "MANDATE",
    "NAME_ALONE_INSUFFICIENT": "MANDATE",
    "ECONOMIC_EXPOSURE_UNKNOWN": "ECONOMIC_EXPOSURE",
    "FI_PROFILE_UNROUTED": "PROFILE_ROUTING",
    "MATERIAL_CONTRADICTION": "PARTICIPATION_POLICY",
    "IAT_KIRA_BELOW_80": "PARTICIPATION_POLICY",
    "IAT_OTHER_POSITIVE_WEIGHT": "PARTICIPATION_POLICY",
    "AIS_KATILMA_OVER_50": "PARTICIPATION_POLICY",
    "ZPE_XK_SLEEVE_BELOW_80": "PARTICIPATION_POLICY",
    "HISTORY_INSUFFICIENT": "FI_DATA_COMPLETENESS",
    "FI_INSUFFICIENT_DATA": "FI_DATA_COMPLETENESS",
    "FI_NOT_PUBLISHABLE": "FI_DATA_COMPLETENESS",
    "PARTICIPATION_REVIEW": "PARTICIPATION_GATE",
    UNCLASSIFIED_REVIEW_GATE: "UNCLASSIFIED",
}

_FAMILY_PRECEDENCE = {
    "SOURCE_CAPTURE": 10,
    "PDR_MISSING_OR_STALE": 20,
    "PDR_PARSE": 30,
    "PDR_RECONCILIATION": 40,
    "GOVERNANCE": 50,
    "MANDATE": 60,
    "ECONOMIC_EXPOSURE": 70,
    "PROFILE_ROUTING": 80,
    "PARTICIPATION_POLICY": 90,
    "FI_DATA_COMPLETENESS": 100,
    "PARTICIPATION_GATE": 110,
    "UNCLASSIFIED": 999,
}

_LABELS_TR = {
    "SOURCE_CAPTURE": "Kaynak / veri yakalama",
    "PDR_MISSING_OR_STALE": "PDR eksik veya güncel değil",
    "PDR_PARSE": "PDR ayrıştırma",
    "PDR_RECONCILIATION": "PDR ağırlık mutabakatı",
    "GOVERNANCE": "Danışma kurulu / yönetişim kanıtı",
    "MANDATE": "Fon yetki / strateji kanıtı",
    "ECONOMIC_EXPOSURE": "Ekonomik maruziyet çözümleme",
    "PROFILE_ROUTING": "Fon profili yönlendirme",
    "PARTICIPATION_POLICY": "Katılım politikası / portföy çelişkisi",
    "FI_DATA_COMPLETENESS": "Fund Intelligence veri yeterliliği",
    "PARTICIPATION_GATE": "Katılım inceleme kapısı",
    "UNCLASSIFIED": "Sınıflandırılmamış inceleme kapısı",
}

_ACTIONS_TR = {
    "SOURCE_CAPTURE": "Resmî kaynak yakalama ve tazelik kanıtını kontrol et.",
    "PDR_MISSING_OR_STALE": "Güncel resmî portföy dağılım raporunu tamamla.",
    "PDR_PARSE": "PDR parser kapsamasını ve alan çıkarımını düzelt.",
    "PDR_RECONCILIATION": "PDR ağırlık toplamı/unknown weight mutabakatını düzelt.",
    "GOVERNANCE": "Fon bazlı danışma kurulu/uygunluk kanıtını tamamla.",
    "MANDATE": "Fon bazlı katılım yetki ve yatırım stratejisi kanıtını çöz.",
    "ECONOMIC_EXPOSURE": "Portföy varlıklarını canonical ekonomik maruziyete eşle.",
    "PROFILE_ROUTING": "Canonical FI profile/vehicle yönlendirmesini çöz.",
    "PARTICIPATION_POLICY": "Mandate ile portföy varlıklarının çelişki nedenini incele.",
    "FI_DATA_COMPLETENESS": "Eksik FI boyutlarını resmî veriyle tamamla.",
    "PARTICIPATION_GATE": "Katılım inceleme kapısının alt nedenini araştır.",
    "UNCLASSIFIED": "Review satırında yapılandırılmış neden bulunamadı; kaynak sözleşmesini incele.",
}


@dataclass(frozen=True)
class ReviewReasonPresentation:
    code: str
    family: str
    family_label: str
    action: str
    wrapper: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def parse_reason_text(reason: Any) -> tuple[str, ...]:
    """Parse the existing human-readable scanner reason without changing it.

    The scanner historically embeds HOLDING_GROUP_OUTSIDE_MANDATE with a
    comma-separated asset-group suffix. That suffix is expanded into stable,
    one-group diagnostic codes here so UI/read-model consumers do not need to
    understand the string shape.
    """
    text = str(reason or "").strip()
    if not text:
        return ()

    if ":" in text:
        head, tail = text.split(":", 1)
        if head.strip().lower() in {"review required", "partial", "blocked"}:
            text = tail

    tokens = [token.strip() for token in text.split(",") if token.strip()]
    parsed: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token.startswith("HOLDING_GROUP_OUTSIDE_MANDATE:"):
            first_group = token.split(":", 1)[1].strip()
            groups: list[str] = []
            if first_group in _ASSET_GROUPS:
                groups.append(first_group)

            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor] in _ASSET_GROUPS:
                groups.append(tokens[cursor])
                cursor += 1

            if groups:
                parsed.extend(
                    f"HOLDING_GROUP_OUTSIDE_MANDATE:{group}" for group in groups
                )
                index = cursor
                continue

        if token in _KNOWN_REASON_CODES:
            parsed.append(token)
        index += 1

    return _dedupe(parsed)


def extract_review_reasons(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the best available read-only diagnostic reason set for one row."""
    canonical = _dedupe(tuple(row.get("missing_evidence") or ()))
    detailed = parse_reason_text(row.get("reason"))

    combined = _dedupe((*detailed, *canonical))
    status = str(row.get("scanner_status") or "").strip().upper()
    if status != READY and not combined:
        return (UNCLASSIFIED_REVIEW_GATE,)
    return combined


def reason_family(code: str) -> str:
    if str(code).startswith("HOLDING_GROUP_OUTSIDE_MANDATE:"):
        return "PARTICIPATION_POLICY"
    return _FAMILY_BY_CODE.get(str(code), "UNCLASSIFIED")


def present_reason(code: str) -> ReviewReasonPresentation:
    normalized = str(code or "").strip() or UNCLASSIFIED_REVIEW_GATE
    family = reason_family(normalized)
    return ReviewReasonPresentation(
        code=normalized,
        family=family,
        family_label=_LABELS_TR[family],
        action=_ACTIONS_TR[family],
        wrapper=normalized in _WRAPPER_REASONS,
    )


def present_review_reasons(row: Mapping[str, Any]) -> tuple[ReviewReasonPresentation, ...]:
    return tuple(present_reason(code) for code in extract_review_reasons(row))


def primary_review_reason(row: Mapping[str, Any]) -> ReviewReasonPresentation | None:
    reasons = list(present_review_reasons(row))
    if not reasons:
        return None

    actionable = [reason for reason in reasons if not reason.wrapper]
    pool = actionable or reasons
    return min(
        pool,
        key=lambda reason: (
            _FAMILY_PRECEDENCE.get(reason.family, 999),
            reason.code,
        ),
    )


def actionable_reason_depth(row: Mapping[str, Any]) -> int:
    reasons = present_review_reasons(row)
    actionable = [reason for reason in reasons if not reason.wrapper]
    return len(actionable) if actionable else len(reasons)
