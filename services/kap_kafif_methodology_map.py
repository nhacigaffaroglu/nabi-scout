"""Audit-only KAFİF → NABI mapping. Does not change thresholds or invent translations."""

from __future__ import annotations

from services.kap_kafif_contract import (
    MAPPING_RELATED_NOT_EQUIVALENT,
    MAPPING_UNMAPPED,
    KafifMethodologyMapping,
)


def audit_kafif_to_nabi_mapping() -> tuple[KafifMethodologyMapping, ...]:
    return (
        KafifMethodologyMapping(
            kafif_field="q1_unsuitable_activity_in_articles",
            nabi_field_or_gate="business_activity_screen",
            mapping_status=MAPPING_UNMAPPED,
            note="Official BIST articles-activity gate. Existing NABI business screen uses SIC/segment/10-K evidence, not KAFİF Q1.",
        ),
        KafifMethodologyMapping(
            kafif_field="q2_unsuitable_privilege_in_articles",
            nabi_field_or_gate="",
            mapping_status=MAPPING_UNMAPPED,
            note="No existing NABI Participation field for privilege in articles.",
        ),
        KafifMethodologyMapping(
            kafif_field="q3_prohibited_support_action_or_decision",
            nabi_field_or_gate="",
            mapping_status=MAPPING_UNMAPPED,
            note="No existing NABI Participation field for Standart 1.5 / Rehber 1.D support.",
        ),
        KafifMethodologyMapping(
            kafif_field="q4_direct_non_compliant_activity_or_income",
            nabi_field_or_gate="non_permissible_revenue",
            mapping_status=MAPPING_UNMAPPED,
            note="Official yes/no is not an NPR amount. Existing NPR requires SEC 10-K attribution.",
        ),
        KafifMethodologyMapping(
            kafif_field="non_compliant_income_ratio",
            nabi_field_or_gate="msci.non_permissible_revenue",
            mapping_status=MAPPING_RELATED_NOT_EQUIVALENT,
            note="Both are income screens near 5%, but KAFİF uses official BIST formula (4B+4C-4D)/4E. Do not substitute for NPR.",
        ),
        KafifMethodologyMapping(
            kafif_field="non_compliant_asset_ratio",
            nabi_field_or_gate="msci.cash_and_interest_bearing_to_total_assets",
            mapping_status=MAPPING_RELATED_NOT_EQUIVALENT,
            note="BIST faizli varlık / toplam varlık 33% is not the existing NABI cash+IBS definition.",
        ),
        KafifMethodologyMapping(
            kafif_field="non_compliant_debt_ratio",
            nabi_field_or_gate="msci.total_debt_to_total_assets",
            mapping_status=MAPPING_RELATED_NOT_EQUIVALENT,
            note="BIST faizli borç / toplam varlık 33% is not a license to substitute total_debt or interest_bearing_debt.",
        ),
        KafifMethodologyMapping(
            kafif_field="bist_katilim_tum_membership",
            nabi_field_or_gate="screening_context.EXISTING_CONSTITUENT",
            mapping_status=MAPPING_UNMAPPED,
            note="Existing EXISTING_CONSTITUENT context is MSCI Islamic membership history, not BIST Katılım Tüm.",
        ),
    )
