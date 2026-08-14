from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from services.wealth_adviser_contract import (
    AdviserContext,
    AdviserPreferenceAssessment,
    AdviserUserContext,
    PreferenceAssessmentStatus,
)
from services.wealth_adviser_profile_contract import AdviserGoal, InvestorProfile
from services.wealth_diagnostics_contract import DiagnosticCategory, DiagnosticSeverity

CONCENTRATION_CODES = {
    "CONCENTRATION_SINGLE_HIGH",
    "CONCENTRATION_SINGLE_WATCH",
    "CONCENTRATION_TOP3_HIGH",
    "CONCENTRATION_TOP3_WATCH",
    "CONCENTRATION_ASSET_CLASS_HIGH",
    "CONCENTRATION_ASSET_CLASS_WATCH",
}
CASH_CODES = {"CASH_WEIGHT_HIGH", "CASH_WEIGHT_ELEVATED"}
DRAWDOWN_CODES = {"DRAWDOWN_RAW_SNAPSHOT", "DRAWDOWN_PERFORMANCE"}


def _has_concentration_signal(context: AdviserContext) -> bool:
    for finding in context.findings:
        if finding.diagnostic_code in CONCENTRATION_CODES:
            return True
        if finding.category == DiagnosticCategory.CONCENTRATION.value and finding.severity in {
            DiagnosticSeverity.HIGH.value,
            DiagnosticSeverity.WATCH.value,
        }:
            return True
    return context.portfolio.largest_position_pct >= 40.0


def _has_elevated_cash(context: AdviserContext) -> bool:
    for finding in context.findings:
        if finding.diagnostic_code in CASH_CODES:
            return True
    return context.portfolio.cash_pct >= 50.0


def _has_drawdown_signal(context: AdviserContext) -> bool:
    return any(finding.diagnostic_code in DRAWDOWN_CODES for finding in context.findings)


def build_preference_assessments(
    context: AdviserContext,
    profile: InvestorProfile,
    goals: Sequence[AdviserGoal],
) -> Tuple[AdviserPreferenceAssessment, ...]:
    assessments: List[AdviserPreferenceAssessment] = []
    concentration_pref = profile.concentration_preference
    if concentration_pref and _has_concentration_signal(context):
        if concentration_pref == "AVOID":
            assessments.append(
                AdviserPreferenceAssessment(
                    assessment_id="pref:concentration_conflict",
                    code="CONCENTRATION_PREF_CONFLICT",
                    status=PreferenceAssessmentStatus.POTENTIAL_CONFLICT,
                    severity=DiagnosticSeverity.WATCH.value,
                    profile_field="concentration_preference",
                    profile_value=concentration_pref,
                    diagnostic_code="CONCENTRATION_SINGLE_HIGH",
                    goal_id=None,
                    evidence={
                        "largest_position_pct": context.portfolio.largest_position_pct,
                        "top3_concentration_pct": context.portfolio.top3_concentration_pct,
                    },
                    statement=(
                        "Portföy yoğunlaşması belirttiğiniz 'yoğunlaşmadan kaçın' tercihiyle "
                        "potansiyel çelişki gösterebilir; deterministik yoğunlaşma bulguları "
                        "değişmeden kalır."
                    ),
                    limitations=(
                        "Bu yalnızca tercih-portföy ilişki gözlemidir; tanı şiddeti değiştirilmez.",
                    ),
                )
            )
        elif concentration_pref == "ACCEPT_HIGH":
            assessments.append(
                AdviserPreferenceAssessment(
                    assessment_id="pref:concentration_acceptance",
                    code="CONCENTRATION_ACCEPTANCE",
                    status=PreferenceAssessmentStatus.ALIGNED,
                    severity=DiagnosticSeverity.INFO.value,
                    profile_field="concentration_preference",
                    profile_value=concentration_pref,
                    diagnostic_code="CONCENTRATION_SINGLE_HIGH",
                    goal_id=None,
                    evidence={
                        "largest_position_pct": context.portfolio.largest_position_pct,
                    },
                    statement=(
                        "Yüksek yoğunlaşma, belirttiğiniz yüksek yoğunlaşma toleransıyla "
                        "kısmen uyumlu olabilir; bu, yoğunlaşmanın nesnel olarak düşük "
                        "riskli olduğu anlamına gelmez."
                    ),
                    limitations=(
                        "Deterministik yoğunlaşma yüzdesi ve tanı şiddeti değiştirilmez.",
                    ),
                )
            )
        else:
            assessments.append(
                AdviserPreferenceAssessment(
                    assessment_id="pref:concentration_neutral",
                    code="CONCENTRATION_NEUTRAL",
                    status=PreferenceAssessmentStatus.NEUTRAL,
                    severity=DiagnosticSeverity.INFO.value,
                    profile_field="concentration_preference",
                    profile_value=concentration_pref,
                    diagnostic_code="CONCENTRATION_SINGLE_HIGH",
                    goal_id=None,
                    evidence={"largest_position_pct": context.portfolio.largest_position_pct},
                    statement="Yoğunlaşma bulguları mevcut; tercih alanı orta düzeyde tanımlı.",
                    limitations=(),
                )
            )
    elif concentration_pref == "AVOID":
        assessments.append(
            AdviserPreferenceAssessment(
                assessment_id="pref:concentration_insufficient",
                code="CONCENTRATION_PREF_INSUFFICIENT",
                status=PreferenceAssessmentStatus.INSUFFICIENT_DATA,
                severity=DiagnosticSeverity.INFO.value,
                profile_field="concentration_preference",
                profile_value=concentration_pref,
                diagnostic_code=None,
                goal_id=None,
                evidence={},
                statement="Yoğunlaşma tercihi kayıtlı ancak karşılaştırılacak yeterli yoğunlaşma bulgusu yok.",
                limitations=(),
            )
        )

    liquidity_need = profile.liquidity_need
    if liquidity_need == "HIGH" and _has_elevated_cash(context):
        assessments.append(
            AdviserPreferenceAssessment(
                assessment_id="pref:liquidity_cash_alignment",
                code="LIQUIDITY_CASH_ALIGNMENT",
                status=PreferenceAssessmentStatus.ALIGNED,
                severity=DiagnosticSeverity.INFO.value,
                profile_field="liquidity_need",
                profile_value=liquidity_need,
                diagnostic_code="CASH_WEIGHT_ELEVATED",
                goal_id=None,
                evidence={"cash_pct": context.portfolio.cash_pct},
                statement=(
                    "Yüksek nakit ağırlığı, belirttiğiniz yüksek likidite ihtiyacıyla "
                    "kısmen uyumlu olabilir."
                ),
                limitations=("Nakit oranı yine de deterministik portföy gerçeğidir.",),
            )
        )

    horizon = profile.investment_horizon
    if horizon in {"SHORT", "MEDIUM"} and _has_drawdown_signal(context):
        assessments.append(
            AdviserPreferenceAssessment(
                assessment_id="pref:horizon_drawdown",
                code="HORIZON_DRAWDOWN_CONSIDERATION",
                status=PreferenceAssessmentStatus.POTENTIAL_CONFLICT,
                severity=DiagnosticSeverity.WATCH.value,
                profile_field="investment_horizon",
                profile_value=horizon,
                diagnostic_code="DRAWDOWN_PERFORMANCE",
                goal_id=None,
                evidence={"investment_horizon": horizon},
                statement=(
                    "Kısa/orta vadeli ufuk ile drawdown bulguları birlikte değerlendirilmelidir; "
                    "bu bir işlem önerisi değildir."
                ),
                limitations=("Drawdown tanısı ve şiddeti değiştirilmez.",),
            )
        )

    for goal in goals:
        if goal.goal_type == "INCOME":
            assessments.append(
                AdviserPreferenceAssessment(
                    assessment_id=f"pref:goal_income:{goal.id}",
                    code="INCOME_GOAL_DATA_GAP",
                    status=PreferenceAssessmentStatus.INSUFFICIENT_DATA,
                    severity=DiagnosticSeverity.INFO.value,
                    profile_field=None,
                    profile_value=None,
                    diagnostic_code=None,
                    goal_id=goal.id,
                    evidence={"goal_title": goal.title},
                    statement=(
                        f"'{goal.title}' gelir hedefi için portföyde yeterli gelir odaklı "
                        "deterministik kanıt bulunmuyor."
                    ),
                    limitations=("Gelir hedefi kullanıcı tarafından açıkça kaydedilmiştir.",),
                )
            )
        if goal.currency and context.portfolio.mixed_currency_warning:
            if goal.currency != context.portfolio.base_currency:
                assessments.append(
                    AdviserPreferenceAssessment(
                        assessment_id=f"pref:goal_currency:{goal.id}",
                        code="GOAL_CURRENCY_DATA_GAP",
                        status=PreferenceAssessmentStatus.INSUFFICIENT_DATA,
                        severity=DiagnosticSeverity.INFO.value,
                        profile_field=None,
                        profile_value=None,
                        diagnostic_code="DATA_MIXED_CURRENCY",
                        goal_id=goal.id,
                        evidence={
                            "goal_currency": goal.currency,
                            "portfolio_base_currency": context.portfolio.base_currency,
                        },
                        statement=(
                            "Hedef para birimi ile portföy baz para birimi/FX sınırlamaları "
                            "nedeniyle hedef karşılaştırması sınırlıdır."
                        ),
                        limitations=("Karışık para birimi veri kalitesi uyarısı korunur.",),
                    )
                )

    return tuple(assessments)


def build_adviser_user_context(
    *,
    profile: InvestorProfile,
    goals: Sequence[AdviserGoal],
    context: AdviserContext,
) -> AdviserUserContext:
    assessments = build_preference_assessments(context, profile, goals)
    return AdviserUserContext(
        investor_profile=profile.to_dict(),
        active_goals=tuple(goal.to_dict() for goal in goals if goal.active),
        preference_assessments=assessments,
        missing_profile_fields=profile.missing_fields(),
    )


def preference_summary_lines(assessments: Sequence[AdviserPreferenceAssessment]) -> Tuple[str, ...]:
    return tuple(item.statement for item in assessments)
