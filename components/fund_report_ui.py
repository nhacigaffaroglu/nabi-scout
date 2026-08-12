from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from services.fund_analysis_contract import (
    BENCHMARK_RELATIVE_DISCLAIMER,
    PERFORMANCE_SECTION_TITLE,
    PERFORMANCE_UNAVAILABLE_MESSAGE,
    PRICE_RETURN_DISCLAIMER,
    RETURN_1Y_INSUFFICIENT_MESSAGE,
    RISK_SECTION_TITLE,
    FundAnalysisResult,
    history_coverage_caption,
)
from services.participation_intelligence_contract import (
    PARTICIPATION_DISCLAIMER_SHORT,
    PARTICIPATION_SOURCE_CONFIGURED,
    ParticipationAssessment,
)
from services.participation_intelligence_service import (
    get_participation_assessment_for_fund,
)
from services.fund_report_service import (
    COLD_OPEN_BANNER,
    LIVE_DATA_PROMPT,
    SHARIAH_DISCLAIMER,
    FundReportViewModel,
)


def format_compact_number(value: float) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:,.0f}"


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _resolve_participation_assessment(
    *,
    symbol: str,
    live_result: Optional[FundAnalysisResult],
    tracked_row: Optional[Dict[str, Any]],
) -> Optional[ParticipationAssessment]:
    if live_result is not None and live_result.participation_assessment is not None:
        return live_result.participation_assessment
    normalized = str(symbol or "").strip().upper()
    if not normalized and tracked_row:
        normalized = str(tracked_row.get("symbol") or "").strip().upper()
    if normalized:
        return get_participation_assessment_for_fund(normalized)
    return None


def _format_source_label(source: Optional[str]) -> str:
    return str(source or "—")


def render_participation_assessment(assessment: ParticipationAssessment) -> None:
    if assessment.is_configured_only():
        st.info("Katılım bilgisi: Yapılandırılmış")
    else:
        st.caption(f"Katılım durumu: {assessment.status}")

    st.markdown(f"**Durum:** {assessment.status}")
    st.markdown(f"**Kaynak:** {_format_source_label(assessment.source)}")
    st.markdown(f"**Güven:** {assessment.confidence}")

    if assessment.methodology_label:
        version = assessment.methodology_version or "—"
        st.markdown(
            f"**Metodoloji:** {assessment.methodology_label} ({version})"
        )
    elif assessment.is_configured_only():
        st.markdown("**Bağımsız metodoloji taraması:** yapılmadı")

    if assessment.as_of_date is not None:
        st.caption(f"Tarih: {assessment.as_of_date.isoformat()}")

    for warning in assessment.warnings:
        st.caption(warning)

    st.caption(assessment.disclaimer)


def format_tracked_participation_label(row: dict) -> str:
    symbol = str(row.get("symbol") or "").strip().upper()
    if symbol:
        assessment = get_participation_assessment_for_fund(symbol)
        if assessment.is_configured_only():
            return (
                f"Katılım bilgisi: Yapılandırılmış ({assessment.status})"
            )
    status = row.get("participation_status")
    if row.get("participation_source") == PARTICIPATION_SOURCE_CONFIGURED and status:
        return f"Katılım bilgisi: Yapılandırılmış ({status})"
    if status:
        return f"Katılım: {status}"
    return "Katılım: —"


def render_live_unavailable_prompt() -> None:
    st.info(LIVE_DATA_PROMPT)


def render_participation_section(
    *,
    tracked_row: Optional[Dict[str, Any]],
    live_result: Optional[FundAnalysisResult],
    symbol: Optional[str] = None,
) -> None:
    st.subheader("Katılım")
    st.caption(PARTICIPATION_DISCLAIMER_SHORT)

    resolved_symbol = (
        str(symbol or "").strip().upper()
        or (live_result.symbol if live_result else "")
        or str((tracked_row or {}).get("symbol") or "").strip().upper()
    )
    assessment = _resolve_participation_assessment(
        symbol=resolved_symbol,
        live_result=live_result,
        tracked_row=tracked_row,
    )
    if assessment is not None:
        render_participation_assessment(assessment)
        return

    st.caption("Katılım: —")


def render_identity_section(view: FundReportViewModel) -> None:
    st.subheader("Fon kimliği")
    st.markdown(f"**{view.symbol}** · {view.fund_name}")

    live = view.live_result
    exchange = (live.exchange if live else None) or (
        (view.tracked_row or {}).get("exchange")
    )
    asset_class = (live.asset_class if live else None) or (
        (view.tracked_row or {}).get("asset_class")
    )
    inception_date = live.inception_date if live else None

    identity_parts = []
    if exchange:
        identity_parts.append(f"Borsa: {exchange}")
    if asset_class:
        identity_parts.append(f"Sınıf: {asset_class}")
    if inception_date:
        identity_parts.append(f"Kuruluş: {inception_date}")

    if identity_parts:
        st.caption(" · ".join(identity_parts))
    else:
        st.caption("Ek kimlik alanları: —")

    if live and live.benchmark:
        st.caption(f"Endeks / benchmark: {live.benchmark}")
        st.caption(BENCHMARK_RELATIVE_DISCLAIMER)


def render_cost_section(live_result: Optional[FundAnalysisResult]) -> None:
    st.subheader("Maliyet")
    if live_result is None:
        render_live_unavailable_prompt()
        return

    cols = st.columns(2)
    cols[0].metric(
        "Gider oranı",
        f"%{live_result.expense_ratio:.2f}"
        if live_result.expense_ratio is not None
        else "—",
    )
    cols[1].metric(
        "Dağıtım getirisi",
        f"%{live_result.distribution_yield:.2f}"
        if live_result.distribution_yield is not None
        else "—",
    )


def render_portfolio_section(live_result: Optional[FundAnalysisResult]) -> None:
    st.subheader("Portföy")
    if live_result is None:
        render_live_unavailable_prompt()
        return

    st.metric(
        "Holdings",
        live_result.holdings_count if live_result.holdings_count is not None else "—",
    )

    if live_result.top_holdings:
        holdings_df = pd.DataFrame(
            [
                {
                    "Sembol": holding.symbol or "—",
                    "Ad": holding.name or "—",
                    "Ağırlık (%)": holding.weight_pct,
                }
                for holding in live_result.top_holdings
            ]
        )
        st.dataframe(holdings_df, use_container_width=True, hide_index=True)
    else:
        st.caption("Top holdings verisi yok.")

    if live_result.sector_weights:
        sector_df = pd.DataFrame(
            [
                {"Sektör": sector, "Ağırlık (%)": weight}
                for sector, weight in live_result.sector_weights.items()
            ]
        )
        st.markdown("**Sektör ağırlıkları**")
        st.dataframe(sector_df, use_container_width=True, hide_index=True)


def render_concentration_section(live_result: Optional[FundAnalysisResult]) -> None:
    st.subheader("Yoğunlaşma")
    if live_result is None:
        render_live_unavailable_prompt()
        return

    st.metric(
        "Top-10 yoğunluk",
        f"%{live_result.top10_concentration_pct:.1f}"
        if live_result.top10_concentration_pct is not None
        else "—",
    )


def render_fund_performance_risk(fund: FundAnalysisResult) -> None:
    performance = fund.performance_metrics
    risk = fund.risk_metrics
    has_metrics = fund.has_performance_or_risk_metrics()

    if not has_metrics:
        st.markdown(f"**{PERFORMANCE_SECTION_TITLE}**")
        message = PERFORMANCE_UNAVAILABLE_MESSAGE
        if fund.price_history_status == "RATE_LIMIT":
            message = (
                "Veri sağlayıcı limiti nedeniyle fiyat geçmişi alınamadı; "
                "performans/risk metrikleri hesaplanamadı."
            )
        elif fund.price_history_status in {"PLAN_RESTRICTED", "PREMIUM_REQUIRED"}:
            message = (
                "Fiyat geçmişi mevcut plan kapsamında erişilemedi; "
                "performans/risk metrikleri hesaplanamadı."
            )
        st.info(message)
        for warning in fund.performance_warnings:
            st.warning(warning)
        return

    if performance and performance.has_any_return():
        st.markdown(f"**{PERFORMANCE_SECTION_TITLE}**")
        perf_cols = st.columns(2)
        perf_cols[0].metric(
            "1A fiyat getirisi",
            format_pct(performance.return_1m_pct),
        )
        perf_cols[1].metric(
            "YBB fiyat getirisi",
            format_pct(performance.return_ytd_pct),
        )
        if performance.return_1y_pct is not None:
            st.metric("1Y fiyat getirisi", format_pct(performance.return_1y_pct))
        elif not performance.history_is_full_year:
            st.caption(RETURN_1Y_INSUFFICIENT_MESSAGE)
        if not performance.history_is_full_year and performance.observation_count > 0:
            st.caption(history_coverage_caption(performance.observation_count))
        st.caption(PRICE_RETURN_DISCLAIMER)
        for warning in performance.warnings:
            st.warning(warning)

    if risk and risk.has_any_metric():
        st.markdown(f"**{RISK_SECTION_TITLE}**")
        risk_cols = st.columns(2)
        risk_cols[0].metric(
            "Yıllıklandırılmış oynaklık (fiyat)",
            format_pct(risk.annualized_volatility_pct),
        )
        risk_cols[1].metric(
            "Maksimum düşüş (fiyat)",
            format_pct(risk.max_drawdown_pct),
        )
        label_parts = [
            label
            for label in (risk.volatility_label, risk.drawdown_label)
            if label
        ]
        if label_parts:
            st.caption(" · ".join(label_parts))

    for warning in fund.performance_warnings:
        if warning not in (performance.warnings if performance else ()):
            st.warning(warning)


def render_performance_risk_section(live_result: Optional[FundAnalysisResult]) -> None:
    if live_result is None:
        st.subheader("Performans ve risk")
        render_live_unavailable_prompt()
        return
    render_fund_performance_risk(live_result)


def render_data_quality_section(live_result: Optional[FundAnalysisResult]) -> None:
    st.subheader("Veri kalitesi")
    if live_result is None:
        render_live_unavailable_prompt()
        return

    st.caption(
        "Boyut gözlemleri fon/ETF açıklayıcı boyutlarıdır; "
        "NABI equity skoru veya yatırım tavsiyesi değildir."
    )

    quality_cols = st.columns(2)
    quality_cols[0].metric(
        "Veri tamlığı",
        f"%{live_result.data_completeness_pct:.0f}",
    )
    quality_cols[1].metric("Güven", live_result.analysis_confidence)

    if live_result.endpoint_status:
        status_text = ", ".join(
            f"{key}: {value}"
            for key, value in live_result.endpoint_status.items()
        )
        st.caption(f"Sağlayıcı uç noktaları: {status_text}")

    if live_result.dimension_scores:
        st.markdown("**Boyut gözlemleri**")
        for dimension in live_result.dimension_scores:
            st.write(
                f"**{dimension.dimension}** — {dimension.score:.0f}/100 · "
                f"{dimension.observation}"
            )

    if live_result.labels:
        st.markdown("**Etiketler:** " + ", ".join(f"`{label}`" for label in live_result.labels))

    for warning in live_result.warnings:
        st.warning(warning)

    if live_result.unsupported_fields:
        st.caption(
            "Doğrulanamayan alanlar: "
            + ", ".join(live_result.unsupported_fields)
        )


def render_tracking_metadata_section(
    *,
    tracked_row: Optional[Dict[str, Any]],
    is_tracked: bool,
    format_datetime,
) -> None:
    st.subheader("Takip metadata")
    if not is_tracked or not tracked_row:
        st.caption("Takip kaydı yok.")
        return

    last_updated = tracked_row.get("last_reviewed_at") or tracked_row.get("updated_at")
    last_updated_label = format_datetime(last_updated) if last_updated else "—"
    st.caption(f"Son takip güncellemesi: {last_updated_label}")

    if tracked_row.get("data_provider"):
        st.caption(f"Veri kaynağı: {tracked_row['data_provider']}")
    if tracked_row.get("resolution_source"):
        st.caption(f"Çözümleme kaynağı: {tracked_row['resolution_source']}")
    st.caption("Takip durumu: takip ediliyor")


def render_tracked_provider_notice(
    fund: Optional[FundAnalysisResult],
    *,
    is_tracked: bool,
) -> None:
    if not is_tracked or fund is None:
        return
    if fund.price_history_status == "RATE_LIMIT":
        st.info("Canlı fon verisi şu an alınamadı. Takip kaydı korunuyor.")
    elif fund.price_history_status in {"PLAN_RESTRICTED", "PREMIUM_REQUIRED"}:
        st.info("Canlı veri mevcut plan kapsamında erişilemedi. Takip kaydı korunuyor.")


def render_fund_report(view: FundReportViewModel, *, format_datetime) -> None:
    for message in view.state_messages:
        if message == COLD_OPEN_BANNER:
            st.warning(message)
        elif "takip listesinde değil" in message.lower():
            st.warning(message)
        else:
            st.info(message)

    render_identity_section(view)
    render_participation_section(
        tracked_row=view.tracked_row,
        live_result=view.live_result,
        symbol=view.symbol,
    )
    render_cost_section(view.live_result)
    render_portfolio_section(view.live_result)
    render_concentration_section(view.live_result)
    render_performance_risk_section(view.live_result)
    render_data_quality_section(view.live_result)
    render_tracking_metadata_section(
        tracked_row=view.tracked_row,
        is_tracked=view.is_tracked,
        format_datetime=format_datetime,
    )
