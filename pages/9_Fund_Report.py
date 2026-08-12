import streamlit as st

from components.fund_report_ui import render_fund_report, render_tracked_provider_notice
from repositories.tracked_fund_repository import TrackedFundRepository
from repositories.candidate_repository import CandidateRepository
from repositories.scan_repository import ScanRepository
from services.alpha_vantage_client import AlphaVantageClient
from services.fmp_client import FMPClient, FMPError
from services.free_universe_client import FreeUniverseClient
from services.fund_report_service import (
    FUND_REPORT_QUERY_PARAM,
    FUND_REPORT_SESSION_LIVE,
    FUND_REPORT_SESSION_RESOLVED,
    FUND_REPORT_SESSION_SYMBOL,
    build_fund_report_view,
    resolve_requested_symbol,
)
from services.manual_analysis_service import analyze_security, refresh_tracked_fund_metadata
from services.scanner_v8_engine import ScannerV8Engine
from services.sec_financial_client import SECFinancialClient
from services.symbol_resolver_service import SymbolNotFoundError
from services.supabase_client import get_supabase_client
from services.ui import configure_page, render_sidebar
from services.ui_formatters import format_datetime_tr

configure_page("Fund Report | NABI Scout", "📊")
render_sidebar()

st.title("📊 Fon Raporu")

client = get_supabase_client()
tracked_fund_repo = TrackedFundRepository(client)
candidate_repo = CandidateRepository(client)
scan_repo = ScanRepository(client)


@st.cache_data(ttl=3600, show_spinner=False)
def load_sec_company_lookup(contact_email: str) -> dict:
    if not contact_email.strip():
        return {}
    rows = FreeUniverseClient(contact_email=contact_email.strip()).get_sec_companies()
    return {
        str(row.get("symbol") or "").strip().upper(): row
        for row in rows
        if row.get("symbol")
    }


def _refresh_live_fund_analysis(symbol: str):
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        st.error("Sembol gerekli.")
        return None
    try:
        sec_lookup = load_sec_company_lookup("nabi-scout@example.com")
        fmp_client = FMPClient.from_streamlit_secrets()
        alpha_vantage_client = AlphaVantageClient.from_streamlit_secrets()
        sec_client = SECFinancialClient(contact_email="nabi-scout@example.com")
        engine = ScannerV8Engine(fmp_client, sec_client)
        with st.spinner(f"{normalized} canlı veri yenileniyor..."):
            return analyze_security(
                normalized,
                candidate_repo=candidate_repo,
                scan_repo=scan_repo,
                fmp_client=fmp_client,
                alpha_vantage_client=alpha_vantage_client,
                tracked_fund_repo=tracked_fund_repo,
                sec_client=sec_client,
                sec_lookup=sec_lookup,
                engine=engine,
            )
    except SymbolNotFoundError:
        st.error("Sembol bulunamadı.")
    except FMPError as exc:
        if exc.error_class == "rate_limit":
            st.warning("Veri sağlayıcı limiti nedeniyle analiz şu an tamamlanamadı.")
        else:
            st.error(f"Analiz sırasında veri hatası oluştu: {exc}")
    except Exception as exc:
        st.error(f"Canlı veri yenilenemedi: {exc}")
    return None


def _return_to_dashboard() -> None:
    st.session_state.pop(FUND_REPORT_SESSION_SYMBOL, None)
    if FUND_REPORT_QUERY_PARAM in st.query_params:
        del st.query_params[FUND_REPORT_QUERY_PARAM]
    st.switch_page("pages/1_Dashboard.py")


requested_symbol = resolve_requested_symbol(
    session_symbol=st.session_state.get(FUND_REPORT_SESSION_SYMBOL),
    query_symbol=st.query_params.get(FUND_REPORT_QUERY_PARAM),
)

if not requested_symbol:
    st.info("Fon raporu açmak için Dashboard'daki takip edilen fonlardan «Fon Raporu» seçin.")
    if st.button("← Dashboard"):
        _return_to_dashboard()
    st.stop()

st.session_state[FUND_REPORT_SESSION_SYMBOL] = requested_symbol
st.query_params[FUND_REPORT_QUERY_PARAM] = requested_symbol

tracked_row = tracked_fund_repo.get_by_symbol(requested_symbol)
candidate_row = candidate_repo.get_by_symbol(requested_symbol)
session_live = st.session_state.get(FUND_REPORT_SESSION_LIVE)
session_resolved = st.session_state.get(FUND_REPORT_SESSION_RESOLVED)
manual_result = st.session_state.get("manual_analysis_result")

analysis_kind = None
live_result = session_live
resolved = session_resolved

if (
    manual_result is not None
    and str(manual_result.symbol or "").strip().upper() == requested_symbol
):
    analysis_kind = manual_result.analysis_kind
    if live_result is None and manual_result.fund_result is not None:
        live_result = manual_result.fund_result
    if resolved is None and manual_result.resolved is not None:
        resolved = manual_result.resolved

had_tracked_context = bool(st.session_state.get("fund_report_had_tracked_context"))
if tracked_row is not None:
    st.session_state["fund_report_had_tracked_context"] = True

view = build_fund_report_view(
    requested_symbol,
    tracked_row=tracked_row,
    live_result=live_result,
    resolved=resolved,
    analysis_kind=analysis_kind,
    had_tracked_context=had_tracked_context and tracked_row is None,
    candidate_row=candidate_row,
)

if not view.entry_allowed:
    st.error(view.block_reason or "Fon raporu açılamadı.")
    if st.button("← Dashboard", key="fund_report_blocked_dashboard"):
        _return_to_dashboard()
    st.stop()

header_left, header_right = st.columns([4, 1])
with header_left:
    st.markdown(f"## {view.symbol} — {view.fund_name}")
    st.caption("ETF / fon raporu — equity NABI skoru uygulanmaz.")
with header_right:
    if st.button("← Dashboard", key="fund_report_back_dashboard", use_container_width=True):
        _return_to_dashboard()

action_cols = st.columns([1, 1, 2])
with action_cols[0]:
    refresh_clicked = st.button(
        "Canlı veriyi yenile",
        type="primary",
        key="fund_report_refresh_live",
    )
with action_cols[1]:
    metadata_refresh_disabled = not (
        view.is_tracked and view.has_live_data and view.live_result is not None
    )
    metadata_refresh_clicked = st.button(
        "Kayıtlı bilgileri güncelle",
        key="fund_report_refresh_metadata",
        disabled=metadata_refresh_disabled,
        help=(
            "Canlı veri oturumu gerekir. Önce «Canlı veriyi yenile» kullanın."
            if metadata_refresh_disabled
            else None
        ),
    )

if refresh_clicked:
    analysis = _refresh_live_fund_analysis(requested_symbol)
    if analysis is not None:
        if analysis.analysis_kind != "fund" or analysis.fund_result is None:
            st.error("Sembol güvenilir biçimde fon/ETF olarak doğrulanamadı.")
        else:
            st.session_state[FUND_REPORT_SESSION_LIVE] = analysis.fund_result
            st.session_state[FUND_REPORT_SESSION_RESOLVED] = analysis.resolved
            st.rerun()

if metadata_refresh_clicked and view.live_result is not None and view.resolved is not None:
    try:
        refresh_tracked_fund_metadata(
            tracked_fund_repo,
            fund_result=view.live_result,
            resolved=view.resolved,
        )
        st.success("Takip metadata güncellendi.")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Takip metadata güncellenemedi: {exc}")

render_tracked_provider_notice(view.live_result, is_tracked=view.is_tracked)
render_fund_report(view, format_datetime=format_datetime_tr)
