"""BIST official Participation policy. Distinct from MSCI. No production writes."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from services.bist_katilim_tum_contract import (
    MEMBERSHIP_MEMBER,
    MEMBERSHIP_NOT_LISTED,
    MEMBERSHIP_SOURCE_UNAVAILABLE,
    BistKatilimMembership,
)
from services.bist_official_participation_contract import (
    BASIS_IDENTITY_MISMATCH,
    BASIS_KAFIF_INCOMPLETE,
    BASIS_KAFIF_MISSING,
    BASIS_KAFIF_STALE,
    BASIS_MEMBER_COMPLETE_KAFIF,
    BASIS_MEMBERSHIP_UNKNOWN,
    BASIS_NOT_LISTED_NOT_NEGATIVE,
    BASIS_SOURCE_UNAVAILABLE,
    DECISION_AUTHORITY_BIST_OFFICIAL,
    EVIDENCE_INCOMPLETE,
    EVIDENCE_OFFICIAL_ELIGIBILITY,
    EVIDENCE_UNAVAILABLE,
    FRESHNESS_LATEST_KNOWN_OFFICIAL,
    FRESHNESS_POLICY_NEEDS_FOLLOWUP,
    LIMITATION_READ_ONLY,
    METHODOLOGY_NEGATIVE_MAPPING_UNRESOLVED,
    NAMESPACE_BIST_OFFICIAL,
    PERIOD_MISMATCH,
    SHADOW_IDENTITY_REJECTED,
    WATCHER_COMPARE_FIELDS,
    BistOfficialParticipationEvidence,
    KafifFailureFieldAudit,
    KafifNegativeMappingAudit,
)
from services.kap_kafif_contract import KapKafifDocument
from services.participation_intelligence_contract import (
    ASSET_KIND_EQUITY,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    METHODOLOGY_COMPLETENESS_NOT_APPLICABLE,
    PARTICIPATION_DISCLAIMER_FULL,
    PARTICIPATION_SOURCE_BIST_OFFICIAL,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    ParticipationAssessment,
)


def audit_kafif_negative_failure_semantics() -> KafifNegativeMappingAudit:
    """Official KAFİF fields are disclosures, not parsed pass/fail verdicts."""
    fields = (
        KafifFailureFieldAudit(
            kafif_field="q1_unsuitable_activity",
            official_question_or_formula=(
                "1) Esas sözleşmede Katılım Finansı İlkelerine uygun olmayan "
                "faaliyet alanı yer alıyor mu?"
            ),
            explicit_official_fail_flag=False,
            safe_for_automatic_uygun_degil=False,
            note=(
                "EVET/HAYIR disclosure only. No official result field. "
                "EVET is not licensed as UYGUN_DEGIL; articles may list unused fields."
            ),
        ),
        KafifFailureFieldAudit(
            kafif_field="q2_unsuitable_privilege",
            official_question_or_formula=(
                "2) Esas sözleşmede Katılım Finansı İlkelerine uygun olmayan "
                "imtiyaz bulunuyor mu?"
            ),
            explicit_official_fail_flag=False,
            safe_for_automatic_uygun_degil=False,
            note="Privilege disclosure is not an official eligibility verdict field.",
        ),
        KafifFailureFieldAudit(
            kafif_field="q3_prohibited_support",
            official_question_or_formula=(
                "3) Standart madde 1.5 / Rehber madde 1.D destek açıklaması veya kararı "
                "bulunuyor mu?"
            ),
            explicit_official_fail_flag=False,
            safe_for_automatic_uygun_degil=False,
            note=(
                "Q3 semantics differ from Q1/Q2/Q4. No official fail flag is parsed. "
                "Do not treat EVET as identical to other questions."
            ),
        ),
        KafifFailureFieldAudit(
            kafif_field="q4_direct_non_compliant",
            official_question_or_formula=(
                "4) Doğrudan Katılım Finansı İlkelerine aykırı faaliyet ve/veya gelir "
                "bulunuyor mu?"
            ),
            explicit_official_fail_flag=False,
            safe_for_automatic_uygun_degil=False,
            note=(
                "Yes/no disclosure, not an NPR amount or official fail flag. "
                "Pilot members remain MEMBER with non-zero official ratios."
            ),
        ),
        KafifFailureFieldAudit(
            kafif_field="non_compliant_income_ratio",
            official_question_or_formula="[(4B+4C-4D)/4E]*100",
            explicit_official_fail_flag=False,
            safe_for_automatic_uygun_degil=False,
            note=(
                "Official ratio is disclosed; no pass/fail result field is parsed. "
                "Non-zero ratios coexist with BIST Katılım Tüm MEMBER."
            ),
        ),
        KafifFailureFieldAudit(
            kafif_field="non_compliant_asset_ratio",
            official_question_or_formula="[5F-5G)/5H]*100",
            explicit_official_fail_flag=False,
            safe_for_automatic_uygun_degil=False,
            note="No official threshold-result field is present on the parsed form.",
        ),
        KafifFailureFieldAudit(
            kafif_field="non_compliant_debt_ratio",
            official_question_or_formula="[(6I-6J)/5H]*100",
            explicit_official_fail_flag=False,
            safe_for_automatic_uygun_degil=False,
            note="No official threshold-result field is present on the parsed form.",
        ),
    )
    return KafifNegativeMappingAudit(
        automatic_uygun_degil_implemented=False,
        methodology_negative_mapping_unresolved=True,
        explicit_safe_failure_fields=(),
        unresolved_fields=tuple(item.kafif_field for item in fields),
        fields=fields,
    )


def kafif_is_applicable(
    kafif: Optional[KapKafifDocument],
    *,
    period_vs_financial_report: str,
) -> tuple[bool, str]:
    """Narrow freshness: latest known official KAFİF + period alignment."""
    if kafif is None:
        return False, BASIS_KAFIF_MISSING
    if period_vs_financial_report == PERIOD_MISMATCH:
        return False, BASIS_KAFIF_STALE
    return True, FRESHNESS_LATEST_KNOWN_OFFICIAL


def _membership_state(membership: Optional[BistKatilimMembership]) -> str:
    if membership is None:
        return ""
    return str(membership.status or "")


def _kafif_period_label(kafif: Optional[KapKafifDocument]) -> str:
    if kafif is None:
        return ""
    year = str(kafif.financial_year or "").strip()
    raw = str(kafif.period_raw or kafif.period or "").strip()
    if year and raw:
        if year in raw:
            return raw
        return f"{year}/{raw}"
    return raw or year


def _explanation(*, status: str, basis: str, kafif: Optional[KapKafifDocument]) -> str:
    period = _kafif_period_label(kafif)
    if status == PARTICIPATION_STATUS_UYGUN:
        if period:
            return (
                f"Uygun — Borsa İstanbul BIST Katılım Tüm üyeliği ve "
                f"{period} KAP KAFİF bildirimi esas alınmıştır."
            )
        return (
            "Uygun — Borsa İstanbul BIST Katılım Tüm üyeliği ve "
            "güncel KAP KAFİF bildirimi esas alınmıştır."
        )
    if basis == BASIS_NOT_LISTED_NOT_NEGATIVE:
        return (
            "Kontrol Et — BIST Katılım Tüm listesinde yer almıyor; "
            "bu tek başına Uygun Değil anlamına gelmez."
        )
    if basis == BASIS_KAFIF_MISSING:
        return (
            "Kontrol Et — BIST Katılım Tüm üyeliği var, ancak uygulanabilir "
            "KAP KAFİF bildirimi bulunamadı."
        )
    if basis == BASIS_KAFIF_INCOMPLETE:
        return (
            "Kontrol Et — KAP KAFİF bildirimi eksik veya belirsiz; "
            "resmi uygunluk kanıtı tamamlanmadı."
        )
    if basis == BASIS_KAFIF_STALE:
        return (
            "Kontrol Et — KAP KAFİF dönemi mevcut finansal dönemle hizalı değil."
        )
    if basis == BASIS_SOURCE_UNAVAILABLE:
        return (
            "Kontrol Et — Borsa İstanbul Katılım kaynağı kullanılamadı; "
            "yokluk olumsuz karar üretmez."
        )
    if basis == BASIS_IDENTITY_MISMATCH:
        return "BIST resmi katılım yolu yalnızca BIST kimliği için geçerlidir."
    return "Kontrol Et — resmi BIST katılım kanıtı yetersiz veya belirsiz."


def _as_of_date(
    membership: Optional[BistKatilimMembership],
    kafif: Optional[KapKafifDocument],
) -> Optional[date]:
    if membership is not None and membership.member is not None:
        raw = str(membership.member.as_of or "").strip()
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                pass
    submitted = str(kafif.submitted_at if kafif is not None else "").strip()
    if submitted and "." in submitted:
        parts = submitted.split(".", 2)
        if len(parts) >= 3 and len(parts[2]) >= 4:
            try:
                return date(int(parts[2][:4]), int(parts[1]), int(parts[0]))
            except ValueError:
                return None
    return None


def apply_bist_official_participation_policy(
    evidence: BistOfficialParticipationEvidence,
) -> BistOfficialParticipationEvidence:
    """Map official BIST evidence to canonical Participation status. No persist."""
    if evidence.nabi_participation_shadow == SHADOW_IDENTITY_REJECTED:
        return BistOfficialParticipationEvidence(
            symbol=evidence.symbol,
            identity_source=evidence.identity_source,
            membership=None,
            kafif=None,
            official_eligibility=EVIDENCE_UNAVAILABLE,
            kafif_evidence_complete=False,
            nabi_participation_shadow=SHADOW_IDENTITY_REJECTED,
            period_vs_financial_report=evidence.period_vs_financial_report,
            financial_report_period=evidence.financial_report_period,
            decision_authority="",
            confidence=CONFIDENCE_LOW,
            decision_basis=BASIS_IDENTITY_MISMATCH,
            explanation=_explanation(
                status="",
                basis=BASIS_IDENTITY_MISMATCH,
                kafif=None,
            ),
            negative_mapping=METHODOLOGY_NEGATIVE_MAPPING_UNRESOLVED,
            freshness_policy=FRESHNESS_POLICY_NEEDS_FOLLOWUP,
            limitation=evidence.limitation or LIMITATION_READ_ONLY,
            persisted=False,
            provenance={
                **dict(evidence.provenance or {}),
                "namespace": NAMESPACE_BIST_OFFICIAL,
                "identity_accepted": False,
                "msci_fields_not_required": True,
                "msci_fields_not_mutated": True,
                "automatic_uygun_degil": False,
            },
        )

    membership = evidence.membership
    kafif = evidence.kafif
    membership_state = _membership_state(membership)
    applicable, applicability = kafif_is_applicable(
        kafif,
        period_vs_financial_report=evidence.period_vs_financial_report,
    )
    kafif_complete = bool(kafif is not None and kafif.complete)

    if membership is not None and membership_state == MEMBERSHIP_SOURCE_UNAVAILABLE:
        status = PARTICIPATION_STATUS_KONTROL_ET
        official = EVIDENCE_UNAVAILABLE
        basis = BASIS_SOURCE_UNAVAILABLE
        authority = DECISION_AUTHORITY_BIST_OFFICIAL
    elif membership is None:
        status = PARTICIPATION_STATUS_KONTROL_ET
        official = EVIDENCE_INCOMPLETE
        basis = BASIS_MEMBERSHIP_UNKNOWN
        authority = DECISION_AUTHORITY_BIST_OFFICIAL
    elif membership_state == MEMBERSHIP_NOT_LISTED:
        status = PARTICIPATION_STATUS_KONTROL_ET
        official = EVIDENCE_INCOMPLETE
        basis = BASIS_NOT_LISTED_NOT_NEGATIVE
        authority = DECISION_AUTHORITY_BIST_OFFICIAL
    elif membership_state != MEMBERSHIP_MEMBER:
        status = PARTICIPATION_STATUS_KONTROL_ET
        official = EVIDENCE_INCOMPLETE
        basis = BASIS_MEMBERSHIP_UNKNOWN
        authority = DECISION_AUTHORITY_BIST_OFFICIAL
    elif kafif is None:
        status = PARTICIPATION_STATUS_KONTROL_ET
        official = EVIDENCE_INCOMPLETE
        basis = BASIS_KAFIF_MISSING
        authority = DECISION_AUTHORITY_BIST_OFFICIAL
    elif not kafif_complete:
        status = PARTICIPATION_STATUS_KONTROL_ET
        official = EVIDENCE_INCOMPLETE
        basis = BASIS_KAFIF_INCOMPLETE
        authority = DECISION_AUTHORITY_BIST_OFFICIAL
    elif not applicable:
        status = PARTICIPATION_STATUS_KONTROL_ET
        official = EVIDENCE_INCOMPLETE
        basis = applicability
        authority = DECISION_AUTHORITY_BIST_OFFICIAL
    else:
        status = PARTICIPATION_STATUS_UYGUN
        official = EVIDENCE_OFFICIAL_ELIGIBILITY
        basis = BASIS_MEMBER_COMPLETE_KAFIF
        authority = DECISION_AUTHORITY_BIST_OFFICIAL

    assert status != PARTICIPATION_STATUS_UYGUN_DEGIL
    if membership_state == MEMBERSHIP_NOT_LISTED:
        assert status == PARTICIPATION_STATUS_KONTROL_ET

    confidence = (
        CONFIDENCE_HIGH if status == PARTICIPATION_STATUS_UYGUN else CONFIDENCE_LOW
    )
    return BistOfficialParticipationEvidence(
        symbol=evidence.symbol,
        identity_source=evidence.identity_source,
        membership=membership,
        kafif=kafif,
        official_eligibility=official,
        kafif_evidence_complete=kafif_complete,
        nabi_participation_shadow=status,
        period_vs_financial_report=evidence.period_vs_financial_report,
        financial_report_period=evidence.financial_report_period,
        decision_authority=authority,
        confidence=confidence,
        decision_basis=basis,
        explanation=_explanation(status=status, basis=basis, kafif=kafif),
        negative_mapping=METHODOLOGY_NEGATIVE_MAPPING_UNRESOLVED,
        freshness_policy=FRESHNESS_POLICY_NEEDS_FOLLOWUP,
        limitation=LIMITATION_READ_ONLY,
        persisted=False,
        provenance={
            "namespace": NAMESPACE_BIST_OFFICIAL,
            "identity_accepted": True,
            "msci_fields_not_required": True,
            "msci_fields_not_mutated": True,
            "automatic_uygun_degil": False,
            "freshness_rule": FRESHNESS_LATEST_KNOWN_OFFICIAL,
            "freshness_followup": FRESHNESS_POLICY_NEEDS_FOLLOWUP,
            "nabi_status_not_persisted": True,
            "source_membership_state": membership_state,
            "source_notification_id": kafif.disclosure_id if kafif is not None else "",
            "source_period": _kafif_period_label(kafif),
            "source_financial_year": kafif.financial_year if kafif is not None else "",
            "membership_as_of": (
                membership.member.as_of
                if membership is not None and membership.member is not None
                else ""
            ),
            "membership_source_url": (
                membership.member.source_url
                if membership is not None and membership.member is not None
                else ""
            ),
            "kafif_source_url": kafif.source_url if kafif is not None else "",
            "kafif_submitted_at": kafif.submitted_at if kafif is not None else "",
            "kafif_applicability": applicability,
        },
    )


def official_decision_compare_key(
    evidence: BistOfficialParticipationEvidence,
) -> dict[str, Any]:
    """Stable identity for a later watcher: new snapshot/KAFİF → re-resolve."""
    provenance = dict(evidence.provenance or {})
    payload = {
        "symbol": evidence.symbol,
        "status": evidence.nabi_participation_shadow,
        "decision_authority": evidence.decision_authority,
        "source_membership_state": provenance.get("source_membership_state", ""),
        "membership_as_of": provenance.get("membership_as_of", ""),
        "source_notification_id": provenance.get("source_notification_id", ""),
        "source_period": provenance.get("source_period", ""),
        "source_financial_year": provenance.get("source_financial_year", ""),
    }
    return {key: payload.get(key, "") for key in WATCHER_COMPARE_FIELDS}


def build_bist_official_assessment(
    evidence: BistOfficialParticipationEvidence,
) -> ParticipationAssessment:
    decided = apply_bist_official_participation_policy(evidence)
    provenance = dict(decided.provenance or {})
    return ParticipationAssessment(
        symbol=decided.symbol,
        asset_kind=ASSET_KIND_EQUITY,
        status=decided.nabi_participation_shadow,
        source=PARTICIPATION_SOURCE_BIST_OFFICIAL,
        confidence=decided.confidence,
        methodology_id=None,
        methodology_version=None,
        methodology_label="Borsa İstanbul BIST Katılım Tüm + KAP KAFİF",
        as_of_date=_as_of_date(decided.membership, decided.kafif),
        business_activity=None,
        financial_screens=(),
        freshness_label=FRESHNESS_POLICY_NEEDS_FOLLOWUP,
        methodology_completeness=METHODOLOGY_COMPLETENESS_NOT_APPLICABLE,
        warnings=(decided.explanation,) if decided.explanation else (),
        evidence={
            "type": "bist_official",
            "namespace": NAMESPACE_BIST_OFFICIAL,
            "decision_authority": decided.decision_authority,
            "decision_basis": decided.decision_basis,
            "confidence": decided.confidence,
            "source_period": provenance.get("source_period", ""),
            "source_notification_id": provenance.get("source_notification_id", ""),
            "source_membership_state": provenance.get("source_membership_state", ""),
            "source_financial_year": provenance.get("source_financial_year", ""),
            "membership_as_of": provenance.get("membership_as_of", ""),
            "membership_source_url": provenance.get("membership_source_url", ""),
            "kafif_source_url": provenance.get("kafif_source_url", ""),
            "kafif_submitted_at": provenance.get("kafif_submitted_at", ""),
            "explanation": decided.explanation,
            "official_eligibility": decided.official_eligibility,
            "period_vs_financial_report": decided.period_vs_financial_report,
            "negative_mapping": decided.negative_mapping,
            "freshness_policy": decided.freshness_policy,
            "msci_fields_not_required": True,
            "msci_fields_not_mutated": True,
            "persisted": False,
            "watcher_compare_key": official_decision_compare_key(decided),
        },
        disclaimer=PARTICIPATION_DISCLAIMER_FULL,
    )


def resolve_canonical_bist_official_participation(
    *,
    symbol: str,
    identity_source: str,
    membership: Optional[BistKatilimMembership],
    kafif: Optional[KapKafifDocument],
    financial_period: str = "",
    financial_period_end: str = "",
):
    """Shadow canonical Participation for BIST official evidence. Returns None if not BIST."""
    from services.bist_official_participation_resolver import (
        resolve_official_bist_participation_evidence,
    )
    from services.participation_assessment_service import ParticipationAssessmentResult

    decided = resolve_official_bist_participation_evidence(
        symbol=symbol,
        identity_source=identity_source,
        membership=membership,
        kafif=kafif,
        financial_period=financial_period,
        financial_period_end=financial_period_end,
    )
    if decided.nabi_participation_shadow == SHADOW_IDENTITY_REJECTED:
        return None
    assessment = build_bist_official_assessment(decided)
    source_pairs: list[tuple[str, str]] = []
    membership_url = str(decided.provenance.get("membership_source_url") or "")
    kafif_url = str(decided.provenance.get("kafif_source_url") or "")
    if membership_url:
        source_pairs.append(("bist_official.membership", membership_url))
    if kafif_url:
        source_pairs.append(("bist_official.kafif", kafif_url))
    return ParticipationAssessmentResult(
        symbol=decided.symbol,
        methodology_id=None,
        resolved_methodology_version=None,
        participation_assessment=assessment,
        financial_screen_result=None,
        financial_inputs=None,
        business_screen_result=None,
        source_evidence=tuple(source_pairs),
        warnings=(decided.explanation,) if decided.explanation else (),
        errors=(),
        provider_status=(("bist_official", "ok"),),
        sec_available=False,
        used_market_capitalization=None,
        missing_capabilities=(),
        screening_context="",
    )
