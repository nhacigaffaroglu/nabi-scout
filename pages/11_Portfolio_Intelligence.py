import streamlit as st

from components.portfolio_intelligence_ui import (
    render_attention_section,
    render_consolidated_exposure_table,
    render_empty_portfolio_onboarding,
    render_portfolio_charts,
    render_portfolio_kpi_cards,
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

st.title("📊 Portfolio Intelligence")
st.caption(
    "Portföy analitiği, kurum/hesap bazlı görünüm, katılım ve NABI araştırma kapsamı. "
    "Sayfa yenilemesinde harici sağlayıcı veya LLM çağrısı yapılmaz."
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

render_portfolio_kpi_cards(dashboard)
st.divider()
render_portfolio_charts(dashboard)
st.divider()
render_attention_section(dashboard)
st.divider()

if not selected_account_id:
    render_consolidated_exposure_table(dashboard)
    st.divider()

st.subheader("Pozisyonlar")
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
