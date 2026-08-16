import streamlit as st

from components.monitor_ui import (
    render_daily_brief_summary,
    render_monitor_feed,
    render_monitor_filters,
)
from components.portfolio_ai_adviser_ui import render_portfolio_ai_adviser_section
from services.auth_service import get_current_user_id
from services.candidate_price_service import CandidatePriceService
from services.daily_portfolio_brief_service import build_daily_portfolio_brief
from services.monitor_intelligence_service import MonitorIntelligenceService
from services.portfolio_ai_adviser_service import PortfolioAIAdviserService
from services.portfolio_intelligence_enrichment_service import build_portfolio_intelligence_dashboard
from services.portfolio_intelligence_service import PortfolioIntelligenceService
from services.portfolio_research_context import build_portfolio_research_context
from services.ui import prepare_protected_page
from services.wealth_core_service import WealthCoreService


client = prepare_protected_page("NABI Monitor | NABI Scout", "📡")
user_id = get_current_user_id(client)
if not user_id:
    st.error("Oturum gerekli.")
    st.stop()

wealth = WealthCoreService(client, user_id)
portfolio = wealth.ensure_default_portfolio()
price_service = CandidatePriceService(client)
intelligence = PortfolioIntelligenceService(wealth, price_service, nabi_client=client)
monitor = MonitorIntelligenceService(client, user_id)
ai_service = PortfolioAIAdviserService(client, user_id)

st.title("📡 Monitör")
st.caption("Bugün ne değişti? Persisted olay akışı — sayfa yenilemesinde LLM/FMP/SEC çağrısı yok.")

with st.spinner("Monitör verileri yükleniyor…"):
    base_view = intelligence.build_view(portfolio, enrich_nabi=True)
    dashboard = build_portfolio_intelligence_dashboard(base_view)
    brief = build_daily_portfolio_brief(
        portfolio=portfolio,
        dashboard=dashboard,
        monitor=monitor,
    )

refresh_col, _ = st.columns([1, 3])
with refresh_col:
    if st.button("Olayları yenile", key="monitor_refresh_events", help="Portföy olaylarını deterministik olarak günceller."):
        with st.spinner("Olay taraması çalışıyor…"):
            created, skipped = monitor.refresh_portfolio_events(portfolio=portfolio, dashboard=dashboard)
        st.session_state["monitor_last_refresh"] = {"created": created, "skipped": skipped}
        st.rerun()

last_refresh = st.session_state.get("monitor_last_refresh")
if last_refresh:
    st.caption(
        f"Son tarama: {last_refresh.get('created', 0)} yeni, "
        f"{last_refresh.get('skipped', 0)} mevcut (dedupe)."
    )

render_daily_brief_summary(brief)

category, review_status, held_only = render_monitor_filters()
events = monitor.list_events(
    portfolio_id=str(portfolio["id"]),
    dashboard=dashboard,
    category=category,
    review_status=review_status,
    held_only=held_only,
    limit=100,
)

selected_event_id = st.session_state.get("monitor_selected_event_id")


def _mark_reviewed(event_id: str) -> None:
    monitor.mark_reviewed(event_id)
    st.rerun()


def _dismiss(event_id: str) -> None:
    monitor.dismiss(event_id)
    st.rerun()


def _select_for_ai(event_id: str) -> None:
    st.session_state["monitor_selected_event_id"] = event_id
    st.rerun()


render_monitor_feed(
    events,
    on_review=_mark_reviewed,
    on_dismiss=_dismiss,
    on_ai=_select_for_ai,
)

st.divider()
portfolio_context = build_portfolio_research_context(dashboard)
selected_events = tuple(
    event.to_dict()
    for event in events
    if event.event_id == selected_event_id
)
input_payload = ai_service.build_input_payload(
    portfolio_context=portfolio_context,
    brief=brief,
    selected_events=selected_events,
)
identity = ai_service.compute_semantic_identity(input_payload)
cached = st.session_state.get("portfolio_ai_cached_view")
cached_identity = st.session_state.get("portfolio_ai_cached_identity")
persisted = ai_service.fetch_persisted(
    portfolio_id=str(portfolio["id"]),
    semantic_identity=identity,
)
display_response = persisted or (cached if cached_identity == identity else None)
stale = persisted is not None and cached_identity not in (None, identity)


def _generate_ai() -> None:
    result = ai_service.generate(
        portfolio_id=str(portfolio["id"]),
        portfolio_context=portfolio_context,
        brief=brief,
        selected_events=selected_events,
        cached_view=cached,
        cached_identity=cached_identity,
    )
    st.session_state["portfolio_ai_cached_view"] = result
    st.session_state["portfolio_ai_cached_identity"] = identity
    st.rerun()


render_portfolio_ai_adviser_section(
    portfolio_id=str(portfolio["id"]),
    response=display_response,
    semantic_identity=identity,
    stale=stale,
    on_generate=_generate_ai,
)
