from __future__ import annotations

from datetime import date
from typing import Optional

from config.participation_catalog import (
    CATALOG_NAME,
    configured_participation_for_symbol,
    is_configured_participation_symbol,
    normalize_catalog_symbol,
)
from services.participation_intelligence_contract import (
    ASSET_KIND_FUND,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    METHODOLOGY_COMPLETENESS_NONE,
    METHODOLOGY_COMPLETENESS_NOT_APPLICABLE,
    PARTICIPATION_DISCLAIMER_FULL,
    PARTICIPATION_SOURCE_CONFIGURED,
    PARTICIPATION_SOURCE_UNKNOWN,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    ParticipationAssessment,
)


def build_configured_assessment(
    symbol: str,
    *,
    asset_kind: str = ASSET_KIND_FUND,
    as_of_date: Optional[date] = None,
) -> ParticipationAssessment:
    normalized = normalize_catalog_symbol(symbol)
    catalog_entry = configured_participation_for_symbol(normalized)
    if catalog_entry is None:
        raise ValueError(f"Symbol is not configured for participation catalog: {symbol}")

    status, _legacy_score = catalog_entry
    return ParticipationAssessment(
        symbol=normalized,
        asset_kind=asset_kind,
        status=status,
        source=PARTICIPATION_SOURCE_CONFIGURED,
        confidence=CONFIDENCE_HIGH,
        methodology_id=None,
        methodology_version=None,
        methodology_label=None,
        as_of_date=as_of_date or date.today(),
        business_activity=None,
        financial_screens=(),
        data_completeness_pct=None,
        holdings_coverage_pct=None,
        freshness_label=None,
        methodology_completeness=METHODOLOGY_COMPLETENESS_NOT_APPLICABLE,
        warnings=(
            "Yapılandırılmış katılım metadata'sı; bağımsız metodoloji taraması yapılmadı.",
        ),
        evidence={
            "type": "configured",
            "catalog": CATALOG_NAME,
            "symbol": normalized,
        },
        disclaimer=PARTICIPATION_DISCLAIMER_FULL,
    )


def build_unknown_assessment(
    symbol: str,
    *,
    asset_kind: str = ASSET_KIND_FUND,
    as_of_date: Optional[date] = None,
) -> ParticipationAssessment:
    normalized = normalize_catalog_symbol(symbol)
    return ParticipationAssessment(
        symbol=normalized,
        asset_kind=asset_kind,
        status=PARTICIPATION_STATUS_KONTROL_ET,
        source=PARTICIPATION_SOURCE_UNKNOWN,
        confidence=CONFIDENCE_LOW,
        methodology_id=None,
        methodology_version=None,
        methodology_label=None,
        as_of_date=as_of_date or date.today(),
        business_activity=None,
        financial_screens=(),
        data_completeness_pct=None,
        holdings_coverage_pct=None,
        freshness_label=None,
        methodology_completeness=METHODOLOGY_COMPLETENESS_NONE,
        warnings=(
            "Bağımsız katılım taraması henüz çalıştırılmadı.",
        ),
        evidence={
            "type": "unknown",
            "symbol": normalized,
        },
        disclaimer=PARTICIPATION_DISCLAIMER_FULL,
    )


def get_participation_assessment_for_fund(
    symbol: str,
    *,
    as_of_date: Optional[date] = None,
) -> ParticipationAssessment:
    normalized = normalize_catalog_symbol(symbol)
    if is_configured_participation_symbol(normalized):
        return build_configured_assessment(
            normalized,
            asset_kind=ASSET_KIND_FUND,
            as_of_date=as_of_date,
        )
    return build_unknown_assessment(
        normalized,
        asset_kind=ASSET_KIND_FUND,
        as_of_date=as_of_date,
    )
