"""Official KAP Katılım Finansı İlkeleri Bilgi Formu (KAFİF) vocabulary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.kap_public_contract import public_bildirim_url


SOURCE_PUBLIC_KAP_KAFIF = "PUBLIC_KAP_KAFIF"
KAFIF_FORM_TITLE = "Katılım Finansı İlkeleri Bilgi Formu"

ANSWER_EVET = "EVET"
ANSWER_HAYIR = "HAYIR"

LIMITATION_NETWORK = "PUBLIC_KAFIF_NETWORK_FAILURE"
LIMITATION_HTTP = "PUBLIC_KAFIF_HTTP_ERROR"
LIMITATION_NOT_FOUND = "PUBLIC_KAFIF_UNAVAILABLE"
LIMITATION_STRUCTURE = "PUBLIC_KAFIF_UNEXPECTED_STRUCTURE"
LIMITATION_IDENTITY = "PUBLIC_KAFIF_IDENTITY_MISMATCH"
LIMITATION_PERIOD = "PUBLIC_KAFIF_PERIOD_AMBIGUOUS"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

MAPPING_MAPPED = "MAPPED"
MAPPING_RELATED_NOT_EQUIVALENT = "RELATED_NOT_EQUIVALENT"
MAPPING_UNMAPPED = "UNMAPPED_OFFICIAL_EVIDENCE"


def kafif_bildirim_url(disclosure_id: str) -> str:
    return public_bildirim_url(disclosure_id)


@dataclass(frozen=True)
class KapKafifDiscovery:
    symbol: str
    disclosure_id: str
    submitted_at: str
    financial_year: str
    period: str
    source_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "disclosure_id": self.disclosure_id,
            "submitted_at": self.submitted_at,
            "financial_year": self.financial_year,
            "period": self.period,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class KapKafifDocument:
    symbol: str
    issuer_name: str
    disclosure_id: str
    submitted_at: str
    financial_year: str
    period: str
    period_raw: str
    consolidated: Optional[bool]
    consolidation_raw: str
    presentation_currency: str
    presentation_unit_label: str
    source_url: str
    q1_unsuitable_activity_raw: str
    q2_unsuitable_privilege_raw: str
    q3_prohibited_support_raw: str
    q4_direct_non_compliant_raw: str
    q1_unsuitable_activity: Optional[bool]
    q2_unsuitable_privilege: Optional[bool]
    q3_prohibited_support: Optional[bool]
    q4_direct_non_compliant: Optional[bool]
    non_compliant_income_ratio_raw: str
    non_compliant_asset_ratio_raw: str
    non_compliant_debt_ratio_raw: str
    non_compliant_income_ratio: Optional[float]
    non_compliant_asset_ratio: Optional[float]
    non_compliant_debt_ratio: Optional[float]
    complete: bool
    limitation: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "issuer_name": self.issuer_name,
            "disclosure_id": self.disclosure_id,
            "submitted_at": self.submitted_at,
            "financial_year": self.financial_year,
            "period": self.period,
            "period_raw": self.period_raw,
            "consolidated": self.consolidated,
            "consolidation_raw": self.consolidation_raw,
            "presentation_currency": self.presentation_currency,
            "presentation_unit_label": self.presentation_unit_label,
            "source_url": self.source_url,
            "q1_unsuitable_activity_raw": self.q1_unsuitable_activity_raw,
            "q2_unsuitable_privilege_raw": self.q2_unsuitable_privilege_raw,
            "q3_prohibited_support_raw": self.q3_prohibited_support_raw,
            "q4_direct_non_compliant_raw": self.q4_direct_non_compliant_raw,
            "q1_unsuitable_activity": self.q1_unsuitable_activity,
            "q2_unsuitable_privilege": self.q2_unsuitable_privilege,
            "q3_prohibited_support": self.q3_prohibited_support,
            "q4_direct_non_compliant": self.q4_direct_non_compliant,
            "non_compliant_income_ratio_raw": self.non_compliant_income_ratio_raw,
            "non_compliant_asset_ratio_raw": self.non_compliant_asset_ratio_raw,
            "non_compliant_debt_ratio_raw": self.non_compliant_debt_ratio_raw,
            "non_compliant_income_ratio": self.non_compliant_income_ratio,
            "non_compliant_asset_ratio": self.non_compliant_asset_ratio,
            "non_compliant_debt_ratio": self.non_compliant_debt_ratio,
            "complete": self.complete,
            "limitation": self.limitation,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class KafifMethodologyMapping:
    kafif_field: str
    nabi_field_or_gate: str
    mapping_status: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kafif_field": self.kafif_field,
            "nabi_field_or_gate": self.nabi_field_or_gate,
            "mapping_status": self.mapping_status,
            "note": self.note,
        }


class KapKafifSourceError(RuntimeError):
    pass
