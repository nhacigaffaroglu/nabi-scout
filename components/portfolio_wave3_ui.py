from __future__ import annotations

from typing import Callable, Optional

import pandas as pd
import streamlit as st

from services.portfolio_ai_adviser_contract import PortfolioAIAdviserResponse
from services.portfolio_ai_adviser_service import PortfolioAIAdviserService
from services.portfolio_reference_limits_service import PortfolioReferenceLimitsService
from services.wave3_intelligence_service import Wave3IntelligenceService, Wave3IntelligenceView


def render_construction_section(wave3: Wave3IntelligenceView) -> None:
    st.subheader("Portföy yapısı")
    conc = wave3.construction.concentration
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Top-1", f"{conc.top1_weight_pct:.1f}%" if conc.top1_weight_pct else "—")
    c2.metric("Top-3", f"{conc.top3_weight_pct:.1f}%" if conc.top3_weight_pct else "—")
    c3.metric("Top-5", f"{conc.top5_weight_pct:.1f}%" if conc.top5_weight_pct else "—")
    c4.metric("Nakit", f"{wave3.construction.cash_weight_pct:.1f}%" if wave3.construction.cash_weight_pct else "—")

    st.markdown("**Risk bütçesi (yapısal — VaR değil)**")
    risk_rows = [
        {
            "Boyut": row.dimension,
            "Mevcut": f"{row.current_value:.1f}%" if row.current_value is not None else "—",
            "Eşik": f"{row.threshold:.1f}%" if row.threshold is not None else "—",
            "Durum": row.status,
        }
        for row in wave3.construction.risk_budget
    ]
    if risk_rows:
        st.dataframe(pd.DataFrame(risk_rows), hide_index=True, use_container_width=True)

    st.markdown("**Referans limit karşılaştırması**")
    gap_rows = [
        {
            "Boyut": gap.dimension,
            "Mevcut": f"{gap.current_value:.1f}%" if gap.current_value is not None else "—",
            "Limit": f"{gap.reference_limit:.1f}%" if gap.reference_limit is not None else "—",
            "Gap": f"{gap.gap_pp:+.1f}pp" if gap.gap_pp is not None else "—",
            "Durum": gap.status,
        }
        for gap in wave3.reference_gaps
    ]
    if gap_rows:
        st.dataframe(pd.DataFrame(gap_rows), hide_index=True, use_container_width=True)

    st.markdown("**Maruziyet örtüşmesi**")
    for signal in wave3.construction.overlap_signals[:8]:
        weight = (
            f"{signal.combined_weight_pct:.1f}%"
            if signal.combined_weight_pct is not None
            else "—"
        )
        st.markdown(
            f"- **{signal.label}** ({signal.overlap_type}): "
            f"{signal.symbol_count} sembol, {weight} — {signal.look_through_status}"
        )
        if signal.limitation:
            st.caption(signal.limitation)


def render_reference_limits_editor(
    limits_service: PortfolioReferenceLimitsService,
    portfolio_id: str,
) -> None:
    limits = limits_service.get_limits(portfolio_id)
    with st.expander("Referans limitleri (kullanıcı tanımlı)", expanded=False):
        with st.form("pi_reference_limits"):
            max_single = st.number_input(
                "Max tek pozisyon %",
                value=float(limits.get("max_single_position_pct") or 12.0),
            )
            max_top3 = st.number_input(
                "Max top-3 %",
                value=float(limits.get("max_top3_concentration_pct") or 40.0),
            )
            max_sector = st.number_input(
                "Max sektör %",
                value=float(limits.get("max_sector_pct") or 30.0),
            )
            max_inst = st.number_input(
                "Max kurum %",
                value=float(limits.get("max_institution_pct") or 50.0),
            )
            max_kontrol = st.number_input(
                "Max Kontrol Et %",
                value=float(limits.get("max_kontrol_et_pct") or 15.0),
            )
            min_cash = st.number_input(
                "Min nakit %",
                value=float(limits.get("min_cash_pct") or 5.0),
            )
            min_research = st.number_input(
                "Min araştırma kapsamı %",
                value=float(limits.get("min_research_covered_pct") or 60.0),
            )
            if st.form_submit_button("Limitleri kaydet"):
                limits_service.save_limits(
                    portfolio_id,
                    max_single_position_pct=max_single,
                    max_top3_concentration_pct=max_top3,
                    max_sector_pct=max_sector,
                    max_institution_pct=max_inst,
                    max_kontrol_et_pct=max_kontrol,
                    min_cash_pct=min_cash,
                    min_research_covered_pct=min_research,
                )
                st.success("Referans limitleri kaydedildi.")
                st.rerun()


def render_scenarios_section(
    wave3_service: Wave3IntelligenceService,
    dashboard,
) -> None:
    st.subheader("Deterministik senaryolar")
    st.caption("SCENARIO, NOT FORECAST — olasılık iddiası yok.")
    shock = st.slider("Geniş portföy şoku (%)", -40, 0, -20, key="pi_scenario_shock")
    sector_options = sorted(
        {row.sector for row in dashboard.enriched_positions if row.sector}
    )
    sector = st.selectbox("Sektör şoku (opsiyonel)", ["—", *sector_options])
    symbols = sorted(
        {
            row.valuation.symbol
            for row in dashboard.enriched_positions
            if not row.valuation.is_cash
        }
    )
    symbol = st.selectbox("Sembol şoku (opsiyonel)", ["—", *symbols])
    scenarios = wave3_service.build_scenarios(
        dashboard,
        portfolio_shock_pct=float(shock),
        sector=None if sector == "—" else sector,
        symbol=None if symbol == "—" else symbol,
    )
    for scenario in scenarios:
        st.markdown(f"**{scenario.scenario_label}**")
        if scenario.portfolio_impact_pct is not None:
            st.markdown(
                f"Portföy etkisi: {scenario.portfolio_impact_pct:+.2f}% "
                f"({scenario.portfolio_impact_abs:+.2f} {dashboard.base.base_currency})"
            )
        if scenario.coverage_pct is not None:
            st.caption(f"Kapsam: {scenario.coverage_pct:.1f}% fiyatlı")
        if scenario.excluded_unpriced_symbols:
            st.caption(
                f"Hariç fiyatlanmamış: {', '.join(scenario.excluded_unpriced_symbols[:8])}"
            )
        for assumption in scenario.assumptions:
            st.caption(assumption)


def render_decisions_section(wave3: Wave3IntelligenceView) -> None:
    st.subheader("Karar skor kartı")
    sc = wave3.scorecard
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Değerlendirilen", sc.total_evaluated)
    c2.metric("Pozitif", sc.positive_outcomes)
    c3.metric("Negatif", sc.negative_outcomes)
    c4.metric("Kanıt tam", f"{sc.evidence_complete_pct:.0f}%" if sc.evidence_complete_pct else "—")

    for note in wave3.data_quality_notes:
        st.caption(note)

    if wave3.outcomes:
        rows = [
            {
                "Tarih": row.decision_date[:10],
                "Sembol": row.symbol,
                "Tür": row.decision_type,
                "Sonuç %": (
                    f"{row.percentage_outcome:+.1f}"
                    if row.percentage_outcome is not None
                    else "—"
                ),
                "Durum": row.outcome_status,
            }
            for row in wave3.outcomes[:20]
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    if wave3.learning_insights:
        st.markdown("**Öğrenme içgörüleri (deterministik)**")
        for insight in wave3.learning_insights:
            st.markdown(
                f"- **{insight.insight_type}** ({insight.severity}): "
                f"{insight.description}"
            )
            st.caption(insight.limitation)

    if wave3.timeline:
        st.markdown("**Karar zaman çizelgesi**")
        for entry in wave3.timeline[:10]:
            outcome = (
                f"{entry.outcome_pct:+.1f}%"
                if entry.outcome_pct is not None
                else entry.outcome_status or "—"
            )
            st.markdown(
                f"- {entry.decision_date[:10]} **{entry.symbol}** "
                f"({entry.decision_type}) → {outcome}"
            )


def render_decision_ai_section(
    *,
    portfolio_id: str,
    ai_service: PortfolioAIAdviserService,
    portfolio_context,
    brief,
    wave3: Wave3IntelligenceView,
    on_generate: Callable[[], None],
    response: Optional[PortfolioAIAdviserResponse],
    semantic_identity: str,
) -> None:
    st.subheader("Karar geçmişi AI değerlendirmesi")
    st.caption("Yalnızca açık kullanıcı eylemiyle LLM çağrılır.")
    if response and response.status == "AVAILABLE" and response.executive_summary:
        st.markdown(response.executive_summary)
        for item in response.questions_to_review:
            st.markdown(f"- {item}")
    else:
        st.info("Henüz karar geçmişi AI değerlendirmesi yok.")
    if st.button("Karar geçmişimi AI ile değerlendir", key="pi_decision_ai_generate"):
        on_generate()
