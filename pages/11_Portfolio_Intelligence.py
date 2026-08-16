import streamlit as st

from components.portfolio_ai_adviser_ui import render_portfolio_ai_adviser_section
from components.portfolio_advanced_ui import (
    render_cash_event_form,
    render_cash_flow_section,
    render_change_section,
    render_data_quality_section,
    render_goals_section,
    render_income_section,
    render_journal_section,
    render_opportunity_section,
    render_performance_section,
    render_snapshot_controls,
    render_v13_kpi_row,
)
from components.portfolio_intelligence_ui import (
    render_attention_section,
    render_consolidated_exposure_table,
    render_empty_portfolio_onboarding,
    render_portfolio_charts,
    render_position_filters,
    render_position_table,
)
from components.portfolio_management_ui import (
    render_account_management_panel,
    render_account_scope_filter,
    render_add_holding_form,
    render_create_account_form,
    render_position_management_panel,
)
from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.portfolio_account_helpers import accounts_for_portfolio, format_account_display
from services.portfolio_intelligence_enrichment_service import (
    build_portfolio_intelligence_dashboard,
)
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.daily_portfolio_brief_service import build_daily_portfolio_brief
from services.monitor_intelligence_service import MonitorIntelligenceService
from components.portfolio_wave3_ui import (
    render_construction_section,
    render_decisions_section,
    render_decision_ai_section,
    render_reference_limits_editor,
    render_scenarios_section,
)
from services.portfolio_performance_intelligence_service import (
    PortfolioPerformanceIntelligenceService,
)
from services.portfolio_reference_limits_service import PortfolioReferenceLimitsService
from services.wave3_intelligence_service import Wave3IntelligenceService
from services.ui import prepare_protected_page
from services.wealth_core_service import WealthCoreService


client = prepare_protected_page("Portfolio Intelligence | NABI Scout", "📊")

user_id = get_current_user_id(client)
if not user_id:
    st.error("Oturum gerekli.")
    st.stop()

wealth = WealthCoreService(client, user_id)
portfolio = wealth.ensure_default_portfolio()
accounts = wealth.list_accounts()
portfolio_accounts = accounts_for_portfolio(accounts, str(portfolio["id"]))
accounts_by_id = {str(row["id"]): row for row in accounts}

price_service = CandidatePriceService(client)
intelligence = PortfolioIntelligenceService(
    wealth,
    price_service,
    nabi_client=client,
)
performance_intel = PortfolioPerformanceIntelligenceService(
    wealth,
    nabi_client=client,
)
monitor_service = MonitorIntelligenceService(client, user_id)
portfolio_ai_service = PortfolioAIAdviserService(client, user_id)
wave3_service = Wave3IntelligenceService(client, user_id, wealth)
reference_limits_service = PortfolioReferenceLimitsService(client, user_id)

st.title("📊 Portfolio Intelligence")
st.caption(
    "Wealth OS — portföy analitiği, performans, gelir, hedefler ve araştırma "
    "farkındalığı. Sayfa yenilemesinde harici sağlayıcı veya LLM çağrısı yapılmaz."
)

action_col, scope_col = st.columns([2, 1])
with action_col:
    render_create_account_form(wealth, str(portfolio["id"]))
with scope_col:
    selected_account_id = (
        render_account_scope_filter(portfolio_accounts)
        if portfolio_accounts
        else None
    )

render_add_holding_form(wealth, portfolio, accounts)
render_cash_event_form(wealth, portfolio, accounts)
render_account_management_panel(wealth, portfolio, accounts)
st.divider()

with st.spinner("Portföy analizi yükleniyor…"):
    base_view = intelligence.build_view(
        portfolio,
        enrich_nabi=True,
        account_id=selected_account_id,
    )
    dashboard = build_portfolio_intelligence_dashboard(
        base_view,
        accounts_by_id=accounts_by_id,
        selected_account_id=selected_account_id,
    )
    v13 = performance_intel.build_view(portfolio, dashboard)
    reference_limits = reference_limits_service.get_limits(str(portfolio["id"]))
    wave3 = wave3_service.build_view(
        portfolio=portfolio,
        dashboard=dashboard,
        reference_limits_row=reference_limits,
    )

st.caption(
    f"Fiyat kaynağı: {base_view.price_provider} · "
    f"Sağlayıcı çağrısı: {price_service.fetch_count}"
)

if dashboard.base.total_position_count == 0:
    render_empty_portfolio_onboarding(wealth, portfolio, accounts)
    st.stop()

if selected_account_id:
    st.info(
        f"Kurum filtresi aktif: "
        f"{format_account_display(accounts_by_id.get(selected_account_id))}"
    )

render_v13_kpi_row(v13)
render_snapshot_controls(wealth, portfolio, intelligence)
st.divider()

tab_perf, tab_structure, tab_scenarios, tab_decisions, tab_intel, tab_plan, tab_hold = st.tabs(
    ["Performans", "Yapı", "Senaryolar", "Kararlar", "Zeka", "Planlama", "Pozisyonlar"]
)

with tab_perf:
    render_performance_section(v13)
    st.divider()
    render_income_section(v13)
    st.divider()
    render_cash_flow_section(v13)

with tab_structure:
    render_reference_limits_editor(reference_limits_service, str(portfolio["id"]))
    render_construction_section(wave3)
    st.divider()
    render_portfolio_charts(dashboard)

with tab_scenarios:
    render_scenarios_section(wave3_service, dashboard)
    if v13.goal_projections:
        st.divider()
        st.markdown("**Hedef senaryo etkisi (deterministik)**")
        for goal in v13.goal_projections[:3]:
            st.markdown(f"- **{goal.goal_title}**")
            for scenario in goal.scenarios:
                st.caption(
                    f"{scenario.label}: {scenario.projected_value} "
                    f"(ilerleme {scenario.progress_pct}%) — {scenario.assumptions_note}"
                )

with tab_decisions:
    render_decisions_section(wave3)
    st.divider()
    portfolio_context = build_portfolio_research_context(dashboard, v13=v13)
    brief = build_daily_portfolio_brief(
        portfolio=portfolio,
        dashboard=dashboard,
        monitor=monitor_service,
    )
    decision_review_payload = wave3.to_dict()
    decision_ai_payload = portfolio_ai_service.build_input_payload(
        portfolio_context=portfolio_context,
        brief=brief,
        decision_review=decision_review_payload,
    )
    decision_ai_identity = portfolio_ai_service.compute_semantic_identity(decision_ai_payload)
    decision_ai_persisted = portfolio_ai_service.fetch_persisted(
        portfolio_id=str(portfolio["id"]),
        semantic_identity=decision_ai_identity,
    )

    def _generate_decision_ai() -> None:
        result = portfolio_ai_service.generate(
            portfolio_id=str(portfolio["id"]),
            portfolio_context=portfolio_context,
            brief=brief,
            decision_review=decision_review_payload,
            force_refresh=True,
        )
        st.session_state["pi_decision_ai_view"] = result
        st.rerun()

    render_decision_ai_section(
        portfolio_id=str(portfolio["id"]),
        ai_service=portfolio_ai_service,
        portfolio_context=portfolio_context,
        brief=brief,
        wave3=wave3,
        on_generate=_generate_decision_ai,
        response=decision_ai_persisted or st.session_state.get("pi_decision_ai_view"),
        semantic_identity=decision_ai_identity,
    )

with tab_intel:
    monitor_service.refresh_portfolio_events(
        portfolio=portfolio,
        dashboard=dashboard,
        wave3_view=wave3,
    )
    brief = build_daily_portfolio_brief(
        portfolio=portfolio,
        dashboard=dashboard,
        monitor=monitor_service,
    )
    st.markdown("**Günlük portföy özeti (deterministik)**")
    st.caption(
        f"Toplam olay: {brief.event_counts.get('total', 0)} · "
        f"Yüksek/Kritik: {brief.event_counts.get('high_critical', 0)}"
    )
    if brief.unresolved_attention:
        for item in brief.unresolved_attention[:5]:
            st.markdown(f"- {item}")
    st.divider()
    render_change_section(v13)
    st.divider()
    render_attention_section(dashboard)
    st.divider()
    render_opportunity_section(v13)
    st.divider()
    render_data_quality_section(v13)
    st.divider()
    portfolio_context = build_portfolio_research_context(dashboard, v13=v13)
    ai_payload = portfolio_ai_service.build_input_payload(
        portfolio_context=portfolio_context,
        brief=brief,
    )
    ai_identity = portfolio_ai_service.compute_semantic_identity(ai_payload)
    ai_cached = st.session_state.get("pi_ai_cached_view")
    ai_cached_identity = st.session_state.get("pi_ai_cached_identity")
    ai_persisted = portfolio_ai_service.fetch_persisted(
        portfolio_id=str(portfolio["id"]),
        semantic_identity=ai_identity,
    )
    ai_display = ai_persisted or (ai_cached if ai_cached_identity == ai_identity else None)

    def _generate_pi_ai() -> None:
        result = portfolio_ai_service.generate(
            portfolio_id=str(portfolio["id"]),
            portfolio_context=portfolio_context,
            brief=brief,
            cached_view=ai_cached,
            cached_identity=ai_cached_identity,
        )
        st.session_state["pi_ai_cached_view"] = result
        st.session_state["pi_ai_cached_identity"] = ai_identity
        st.rerun()

    render_portfolio_ai_adviser_section(
        portfolio_id=str(portfolio["id"]),
        response=ai_display,
        semantic_identity=ai_identity,
        stale=ai_persisted is not None and ai_cached_identity not in (None, ai_identity),
        on_generate=_generate_pi_ai,
    )

with tab_plan:
    render_goals_section(v13)
    st.divider()
    render_journal_section(client, user_id, str(portfolio["id"]), accounts)

with tab_hold:
    if not selected_account_id:
        render_consolidated_exposure_table(dashboard)
        st.divider()
    filters = render_position_filters(dashboard)
    render_position_table(
        dashboard,
        symbol_search=filters[0],
        sector_filter=filters[1],
        participation_filter=filters[2],
        research_filter=filters[3],
    )
    render_position_management_panel(wealth, portfolio, accounts, dashboard)

st.divider()
st.markdown("**Şirket raporuna git**")
symbols = sorted(
    {row.valuation.symbol for row in dashboard.enriched_positions if not row.valuation.is_cash}
)
if symbols:
    selected_symbol = st.selectbox("Sembol", symbols, key="pi_report_symbol")
    if st.button("📄 Company Report", type="primary", key="pi_open_company_report"):
        from repositories.candidate_repository import CandidateRepository

        repo = CandidateRepository(client)
        candidate = repo.get_by_symbol(selected_symbol)
        if candidate:
            st.session_state["company_report_candidate"] = candidate
        else:
            st.session_state["company_report_candidate"] = {"symbol": selected_symbol}
        st.query_params["symbol"] = selected_symbol
        st.switch_page("pages/4_Company_Report.py")
