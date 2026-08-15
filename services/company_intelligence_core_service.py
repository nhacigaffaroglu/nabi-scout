from __future__ import annotations

from typing import List, Optional, Tuple

from services.company_business_snapshot import build_business_snapshot
from services.company_earnings_intelligence import build_earnings_intelligence
from services.company_financial_trend_engine import build_financial_trends
from services.company_intelligence_contract import (
    CompanyIntelligenceView,
    DataQualitySection,
    IntelligenceObservation,
)
from services.company_intelligence_data import (
    CompanyProviderBundle,
    bundle_call_summary,
    load_company_provider_bundle,
)
from services.company_news_intelligence import build_catalysts, build_news_intelligence
from services.company_peer_intelligence import build_peer_intelligence
from services.company_valuation_intelligence import (
    build_valuation_intelligence,
    fmp_bundle_has_usable_valuation_ratios,
    valuation_section_has_meaningful_metrics,
)
from services.company_intelligence_sec_valuation import (
    SEC_HYBRID_VALUATION_FAMILY,
    build_sec_hybrid_valuation,
)
from services.company_intelligence_provider_diagnostics import build_provider_diagnostics
from services.company_intelligence_sec_trends import (
    build_financial_trends_from_sec,
    sec_annual_yoy_available,
)
from services.fmp_client import FMPClient, normalize_fmp_error_class
from services.research_eligibility_contract import ResearchEligibilityResult
from services.research_eligibility_service import require_research_allowed


def _build_factual_risks(
    trends,
    earnings,
    valuation,
    peers,
    news,
) -> Tuple[IntelligenceObservation, ...]:
    risks: List[IntelligenceObservation] = []
    if trends:
        for observation in trends.observations:
            if observation.code in {
                "GROSS_MARGIN_COMPRESSION",
                "FCF_DETERIORATION",
                "DEBT_INCREASE",
            }:
                risks.append(
                    IntelligenceObservation(
                        code=f"RISK_{observation.code}",
                        status="CONSIDERATION",
                        statement=observation.statement,
                        metric=observation.metric,
                        value=observation.value,
                        comparison_value=observation.comparison_value,
                        evidence=observation.evidence,
                        source=observation.source,
                        confidence=observation.confidence,
                        period=observation.period,
                        limitations=("Bu bir risk sinyalidir; tahmin veya işlem önerisi değildir.",),
                    )
                )
    if earnings:
        for observation in earnings.observations:
            if observation.code in {"REVENUE_DECELERATION", "EPS_DECELERATION", "FCF_DETERIORATION"}:
                risks.append(
                    IntelligenceObservation(
                        code=f"RISK_{observation.code}",
                        status="CONSIDERATION",
                        statement=observation.statement,
                        metric=observation.metric,
                        value=observation.value,
                        comparison_value=observation.comparison_value,
                        evidence=observation.evidence,
                        source=observation.source,
                        confidence=observation.confidence,
                        period=observation.period,
                        limitations=("Bu bir risk sinyalidir; tahmin veya işlem önerisi değildir.",),
                    )
                )
    if valuation:
        for metric in valuation.metrics:
            if metric.position in {"ABOVE_HISTORICAL_RANGE", "ABOVE_HISTORICAL_MEDIAN"}:
                risks.append(
                    IntelligenceObservation(
                        code="RISK_VALUATION_PREMIUM",
                        status="CONSIDERATION",
                        statement=f"{metric.label} tarihsel medyanın üzerinde.",
                        metric=metric.code,
                        value=metric.current_value,
                        comparison_value=metric.historical_median,
                        evidence=(("position", metric.position),),
                        source="fmp",
                        confidence="MEDIUM",
                        limitations=("Değerleme primi otomatik olarak aşırı değerli anlamına gelmez.",),
                    )
                )
    if news:
        for event in news.events:
            if event.category in {"REGULATORY", "LEGAL"} and event.materiality == "MATERIAL":
                risks.append(
                    IntelligenceObservation(
                        code="RISK_MATERIAL_NEWS_EVENT",
                        status="CONSIDERATION",
                        statement=event.headline,
                        evidence=(("category", event.category), ("materiality", event.materiality)),
                        source=event.source or "fmp",
                        confidence=event.confidence,
                        limitations=("Haber olayı temel etkiyi tek başına kanıtlamaz.",),
                    )
                )
    return tuple(risks)


def _build_data_quality(bundle: CompanyProviderBundle, view_parts) -> DataQualitySection:
    partial: List[str] = []
    if not view_parts["business_snapshot"]:
        partial.append("business_snapshot")
    if not view_parts["financial_trends"]:
        partial.append("financial_trends")
    if not view_parts["earnings"]:
        partial.append("earnings")
    if not view_parts["valuation"]:
        partial.append("valuation")
    if not view_parts["peers"]:
        partial.append("peers")
    if not view_parts["news"]:
        partial.append("news")

    earnings_expectations = False
    if view_parts["earnings"] and view_parts["earnings"].expectations.expectations_available:
        earnings_expectations = True

    valuation_section = view_parts["valuation"]
    historical_valuation = False
    sec_hybrid_valuation = False
    if valuation_section:
        historical_valuation = any(
            metric.historical_median is not None for metric in valuation_section.metrics
        )
        sec_hybrid_valuation = (
            valuation_section.provenance.data_family == SEC_HYBRID_VALUATION_FAMILY
        )
    has_meaningful_valuation = bool(
        valuation_section
        and any(
            metric.meaningful and metric.current_value is not None
            for metric in valuation_section.metrics
        )
    )

    yoy_available = False
    if bundle.income_quarterly:
        from services.company_intelligence_utils import find_yoy_pair

        latest, previous = find_yoy_pair(bundle.income_quarterly)
        yoy_available = latest is not None and previous is not None

    normalized_failures = tuple(
        (
            f"{label}:{normalize_fmp_error_class(error_class)}"
            if ":" in failure
            else failure
        )
        for failure in bundle.failures
        for label, error_class in [
            failure.split(":", 1) if ":" in failure else (failure, failure)
        ]
    )
    provider_diagnostic_details = tuple(
        item.to_dict()
        for item in build_provider_diagnostics(
            bundle.failures,
            recorded=tuple(bundle.provider_diagnostics),
        )
    )

    return DataQualitySection(
        company_profile_available=bool(bundle.profile),
        financial_history_available=bool(bundle.income_quarterly or sec_annual_yoy_available(bundle.sec_financials)),
        quarterly_comparison_available=yoy_available,
        earnings_expectations_available=earnings_expectations,
        valuation_available=bool(
            bundle.ratios_ttm or bundle.key_metrics_ttm or has_meaningful_valuation
        ),
        historical_valuation_available=historical_valuation,
        peer_data_available=bool(bundle.peers),
        news_available=bool(view_parts["news"] and view_parts["news"].events),
        catalyst_data_available=bool(view_parts["catalysts"]),
        warnings=tuple(
            warning
            for warning in (
                "Finansal geçmiş eksik." if not bundle.income_quarterly and not sec_annual_yoy_available(bundle.sec_financials) else None,
                "FMP çeyreklik finansal verisi plan kapsamında değil; Finansal Eğilim SEC yıllık verisinden oluşturuldu."
                if not bundle.income_quarterly and sec_annual_yoy_available(bundle.sec_financials)
                else None,
                "Beklenti verisi yok." if not earnings_expectations else None,
                "FMP değerleme endpoint'leri plan kapsamında değil; SEC yıllık finansallar + piyasa değeri hibrit değerleme kullanıldı."
                if sec_hybrid_valuation
                else None,
                "Tarihsel değerleme yetersiz." if valuation_section and not historical_valuation else None,
                "Rakip verisi yok." if not bundle.peers else None,
                "Haber verisi yok." if not (view_parts["news"] and view_parts["news"].events) else None,
            )
            if warning
        ),
        provider_failures=normalized_failures,
        provider_diagnostic_details=provider_diagnostic_details,
        partial_sections=tuple(partial),
        as_of=bundle.retrieved_at,
    )


class CompanyIntelligenceCoreService:
    def __init__(self, fmp_client: FMPClient) -> None:
        self.fmp = fmp_client
        self._bundle_cache: dict[str, CompanyProviderBundle] = {}

    def load_bundle(
        self,
        symbol: str,
        *,
        research_eligibility: ResearchEligibilityResult,
        refresh: bool = False,
        sec_financials: Optional[dict] = None,
    ) -> CompanyProviderBundle:
        require_research_allowed(research_eligibility, symbol=symbol)
        normalized = symbol.strip().upper()
        if refresh or normalized not in self._bundle_cache:
            self._bundle_cache[normalized] = load_company_provider_bundle(
                self.fmp,
                normalized,
                sec_financials=sec_financials,
            )
        bundle = self._bundle_cache[normalized]
        if sec_financials:
            bundle.sec_financials = dict(sec_financials)
        return bundle

    def build_view(
        self,
        symbol: str,
        *,
        research_eligibility: ResearchEligibilityResult,
        refresh: bool = False,
        sec_financials: Optional[dict] = None,
    ) -> CompanyIntelligenceView:
        require_research_allowed(research_eligibility, symbol=symbol)
        bundle = self.load_bundle(
            symbol,
            research_eligibility=research_eligibility,
            refresh=refresh,
            sec_financials=sec_financials,
        )
        business = build_business_snapshot(bundle) if bundle.profile else None
        trends = build_financial_trends(bundle) if bundle.income_quarterly else None
        if trends is None and bundle.sec_financials:
            trends = build_financial_trends_from_sec(
                bundle.sec_financials,
                symbol=bundle.symbol,
                retrieved_at=bundle.retrieved_at,
            )
        earnings = build_earnings_intelligence(bundle) if bundle.income_quarterly else None
        valuation = None
        if fmp_bundle_has_usable_valuation_ratios(bundle):
            valuation = build_valuation_intelligence(bundle)
        if not valuation_section_has_meaningful_metrics(valuation):
            hybrid_valuation = build_sec_hybrid_valuation(bundle)
            if hybrid_valuation is not None:
                valuation = hybrid_valuation
        peers = build_peer_intelligence(bundle) if bundle.peers or bundle.failures else None
        news = build_news_intelligence(bundle) if bundle.news or any(
            failure.startswith("stock_news") for failure in bundle.failures
        ) else None
        catalysts = build_catalysts(bundle, news.events if news else ())

        view_parts = {
            "business_snapshot": business,
            "financial_trends": trends,
            "earnings": earnings,
            "valuation": valuation,
            "peers": peers,
            "news": news,
            "catalysts": catalysts,
        }
        data_quality = _build_data_quality(bundle, view_parts)
        factual_risks = _build_factual_risks(trends, earnings, valuation, peers, news)

        return CompanyIntelligenceView(
            symbol=bundle.symbol,
            company_name=(business.company_name if business else None),
            as_of=bundle.retrieved_at,
            business_snapshot=business,
            financial_trends=trends,
            earnings=earnings,
            valuation=valuation,
            peers=peers,
            news=news,
            catalysts=catalysts,
            factual_risks=factual_risks,
            data_quality=data_quality,
            provenance=(),
        )

    def call_budget(
        self,
        symbol: str,
        *,
        research_eligibility: ResearchEligibilityResult,
    ) -> dict:
        bundle = self.load_bundle(symbol, research_eligibility=research_eligibility)
        return bundle_call_summary(bundle)
