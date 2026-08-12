from __future__ import annotations

from datetime import date
from typing import Optional

from config.participation_catalog import (
    CATALOG_NAME,
    configured_participation_for_symbol,
    is_configured_participation_symbol,
    normalize_catalog_symbol,
)
from services.participation_financial_contract import ParticipationFinancialScreenResult
from services.participation_intelligence_contract import (
    ASSET_KIND_EQUITY,
    ASSET_KIND_FUND,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    METHODOLOGY_COMPLETENESS_COMPLETE,
    METHODOLOGY_COMPLETENESS_NONE,
    METHODOLOGY_COMPLETENESS_NOT_APPLICABLE,
    METHODOLOGY_COMPLETENESS_PARTIAL,
    PARTICIPATION_DISCLAIMER_FULL,
    PARTICIPATION_SOURCE_CONFIGURED,
    PARTICIPATION_SOURCE_METHODOLOGY,
    PARTICIPATION_SOURCE_UNKNOWN,
    PARTICIPATION_STATUS_KONTROL_ET,
    PARTICIPATION_STATUS_UYGUN,
    PARTICIPATION_STATUS_UYGUN_DEGIL,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_PASS,
    ParticipationAssessment,
    ParticipationRuleResult,
)
from services.participation_methodology_registry import get_methodology


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


def _split_rule_results_for_assessment(
    methodology_id: str,
    rule_results: tuple[ParticipationRuleResult, ...],
) -> tuple[tuple[ParticipationRuleResult, ...], ParticipationRuleResult | None]:
    methodology = get_methodology(methodology_id)
    if methodology is None:
        return rule_results, None

    business_rule_ids = {
        rule.rule_id
        for rule in methodology.rules
        if rule.screen == "business_activity"
    }
    business_results = tuple(
        result for result in rule_results if result.rule_id in business_rule_ids
    )
    financial_results = tuple(
        result for result in rule_results if result.rule_id not in business_rule_ids
    )
    business_activity = business_results[0] if len(business_results) == 1 else None
    if len(business_results) > 1:
        financial_results = financial_results + business_results
        business_activity = None
    return financial_results, business_activity


def _assessment_status_from_financial_screen(
    screen: ParticipationFinancialScreenResult,
) -> str:
    if screen.overall_outcome == RULE_OUTCOME_FAIL:
        return PARTICIPATION_STATUS_UYGUN_DEGIL
    if (
        screen.overall_outcome == RULE_OUTCOME_PASS
        and screen.methodology_complete
    ):
        return PARTICIPATION_STATUS_UYGUN
    return PARTICIPATION_STATUS_KONTROL_ET


def _methodology_completeness_from_screen(
    screen: ParticipationFinancialScreenResult,
) -> str:
    if not screen.financial_rules_evaluated:
        return METHODOLOGY_COMPLETENESS_NONE
    if screen.methodology_complete:
        return METHODOLOGY_COMPLETENESS_COMPLETE
    return METHODOLOGY_COMPLETENESS_PARTIAL


def build_methodology_assessment_from_financial_screen(
    screen: ParticipationFinancialScreenResult,
    *,
    asset_kind: str = ASSET_KIND_EQUITY,
) -> ParticipationAssessment:
    methodology = get_methodology(screen.methodology_id)
    financial_screens, business_activity = _split_rule_results_for_assessment(
        screen.methodology_id,
        screen.rule_results,
    )
    status = _assessment_status_from_financial_screen(screen)
    confidence = (
        CONFIDENCE_MEDIUM
        if screen.financial_rules_evaluated
        else CONFIDENCE_LOW
    )
    warnings = list(screen.warnings)
    if screen.financial_rules_evaluated and not screen.methodology_complete:
        warnings.append(
            "Mevcut finansal alt küme değerlendirildi; tam metodoloji uygunluğu iddia edilmez."
        )

    return ParticipationAssessment(
        symbol=screen.symbol,
        asset_kind=asset_kind,
        status=status,
        source=PARTICIPATION_SOURCE_METHODOLOGY,
        confidence=confidence,
        methodology_id=screen.methodology_id,
        methodology_version=screen.methodology_version,
        methodology_label=methodology.label if methodology else screen.methodology_id,
        as_of_date=screen.as_of_date,
        business_activity=business_activity,
        financial_screens=financial_screens,
        methodology_completeness=_methodology_completeness_from_screen(screen),
        warnings=tuple(warnings),
        evidence={
            "type": "methodology_financial_screen",
            "methodology_id": screen.methodology_id,
            "overall_outcome": screen.overall_outcome,
            "financial_rules_evaluated": screen.financial_rules_evaluated,
            "methodology_complete": screen.methodology_complete,
        },
        disclaimer=PARTICIPATION_DISCLAIMER_FULL,
    )
