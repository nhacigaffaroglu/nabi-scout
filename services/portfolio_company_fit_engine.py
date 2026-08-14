from __future__ import annotations

from typing import Tuple

from services.investment_thesis_contract import InvestmentThesisView
from services.unified_research_contract import (
    PortfolioCompanyFitAssessment,
    WealthExposureContext,
)

HIGH_EXPOSURE_PCT = 15.0
LOW_EXPOSURE_PCT = 3.0


def assess_portfolio_company_fit(
    thesis: InvestmentThesisView | None,
    exposure: WealthExposureContext | None,
) -> Tuple[PortfolioCompanyFitAssessment, ...]:
    if exposure is None:
        return (
            PortfolioCompanyFitAssessment(
                code="DATA_GAP_PORTFOLIO_FIT",
                statement="Portföy maruziyeti bilinmediği için uyum değerlendirmesi sınırlı.",
                confidence="LOW",
                evidence=(("reason", "missing_exposure"),),
            ),
        )

    if not exposure.held:
        if thesis and thesis.thesis_status == "SUPPORTED":
            return (
                PortfolioCompanyFitAssessment(
                    code="THESIS_SUPPORTED_LOW_EXPOSURE",
                    statement="Tez destekleyici görünse de portföyde pozisyon yok.",
                    confidence="MEDIUM",
                    evidence=(
                        ("thesis_status", thesis.thesis_status),
                        ("held", False),
                    ),
                ),
            )
        return (
            PortfolioCompanyFitAssessment(
                code="NOT_HELD",
                statement="Sembol portföyde tutulmuyor.",
                confidence="HIGH",
                evidence=(("held", False),),
            ),
        )

    weight = exposure.portfolio_weight_pct
    if weight is None:
        return (
            PortfolioCompanyFitAssessment(
                code="DATA_GAP_PORTFOLIO_FIT",
                statement="Pozisyon ağırlığı eksik; portföy uyumu tam değerlendirilemedi.",
                confidence="LOW",
                evidence=(("held", True), ("weight_available", False)),
            ),
        )

    if thesis is None:
        return (
            PortfolioCompanyFitAssessment(
                code="DATA_GAP_PORTFOLIO_FIT",
                statement="Yatırım tezi olmadan portföy uyumu sınırlı değerlendirildi.",
                confidence="LOW",
                evidence=(("weight_pct", weight),),
            ),
        )

    high_exposure = weight >= HIGH_EXPOSURE_PCT
    if thesis.thesis_status == "SUPPORTED" and high_exposure:
        return (
            PortfolioCompanyFitAssessment(
                code="COMPANY_THESIS_STRONG_PORTFOLIO_CONCENTRATED",
                statement=(
                    "Tez destekleyici görünürken pozisyon portföyde yüksek ağırlıkta."
                ),
                confidence="MEDIUM",
                evidence=(
                    ("thesis_status", thesis.thesis_status),
                    ("weight_pct", weight),
                ),
            ),
        )
    if thesis.thesis_status == "WEAKENING" and high_exposure:
        return (
            PortfolioCompanyFitAssessment(
                code="THESIS_WEAKENING_HIGH_EXPOSURE",
                statement="Tez zayıflama sinyalleri varken pozisyon yoğun.",
                confidence="HIGH",
                evidence=(
                    ("thesis_status", thesis.thesis_status),
                    ("weight_pct", weight),
                ),
            ),
        )
    if thesis.thesis_status == "MIXED" and high_exposure:
        return (
            PortfolioCompanyFitAssessment(
                code="THESIS_MIXED_HIGH_EXPOSURE",
                statement="Karışık tez ile yüksek portföy maruziyeti birlikte.",
                confidence="MEDIUM",
                evidence=(
                    ("thesis_status", thesis.thesis_status),
                    ("weight_pct", weight),
                ),
            ),
        )
    if thesis.thesis_status == "SUPPORTED" and weight <= LOW_EXPOSURE_PCT:
        return (
            PortfolioCompanyFitAssessment(
                code="THESIS_SUPPORTED_LOW_EXPOSURE",
                statement="Tez destekleyici ancak portföyde düşük ağırlık.",
                confidence="MEDIUM",
                evidence=(
                    ("thesis_status", thesis.thesis_status),
                    ("weight_pct", weight),
                ),
            ),
        )

    return (
        PortfolioCompanyFitAssessment(
            code="NEUTRAL_FIT",
            statement="Tez durumu ile portföy maruziyeti nötr ilişkide.",
            confidence="MEDIUM",
            evidence=(
                ("thesis_status", thesis.thesis_status),
                ("weight_pct", weight),
            ),
        ),
    )
