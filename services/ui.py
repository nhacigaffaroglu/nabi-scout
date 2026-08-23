import streamlit as st
from supabase import Client

from services.auth_dev_config import is_dev_auto_login_enabled
from services.auth_service import is_authenticated, sign_out
from components.nabi_design_system import inject_nabi_theme


PRIMARY_NAV = (
    ("pages/1_Dashboard.py", "Dashboard", "📊"),
    ("pages/10_Wealth.py", "Wealth", "🏦"),
    ("pages/5_Firsatlar.py", "Fırsatlar", "🎯"),
)

HIDDEN_NAV_PAGE_HREFS = (
    "Aday_Detayi",
    "Aday_Havuzu",
    "Evren_Motoru",
    "Scout_Tarama",
    "Research_Monitor",
    "Company_Report",
    "Izleme_Listesi",
    "Portfolio_Intelligence",
    "Monitor",
    "Fund_Report",
    "NABI_Akademi",
)


def hide_retired_streamlit_pages() -> None:
    """Hide technical pages from Streamlit's auto-generated sidebar nav."""
    selectors = ", ".join(
        f'[data-testid="stSidebarNav"] li:has(a[href*="{href}"])'
        for href in HIDDEN_NAV_PAGE_HREFS
    )
    st.markdown(
        f"""
        <style>
        [data-testid="stSidebarNav"] {{ display: none !important; }}
        {selectors} {{ display: none !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def configure_page(title: str, icon: str) -> None:
    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_nabi_theme()
    hide_retired_streamlit_pages()


def render_sidebar() -> None:
    with st.sidebar:
        st.title("NABI Scout 2.0")
        st.caption("Yatırım İşletim Sistemi")
        st.divider()
        st.markdown("**Ana menü**")
        for path, label, icon in PRIMARY_NAV:
            st.page_link(path, label=label, icon=icon)
        st.divider()
        st.page_link("pages/7_Ayarlar.py", label="Ayarlar", icon="⚙️")
        st.caption("Wealth OS verilerini değiştirmez.")
        if is_authenticated():
            email = st.session_state.get("nabi_auth_user_email")
            if email:
                st.caption(f"Oturum: {email}")
            if is_dev_auto_login_enabled():
                st.caption("Geliştirme oturumu: otomatik giriş etkin.")
            elif st.button("Çıkış yap", key="nabi_auth_logout"):
                sign_out()
                st.rerun()


def require_authentication() -> Client:
    from services.auth_service import require_authentication as _require_authentication

    return _require_authentication()


def prepare_protected_page(title: str, icon: str) -> Client:
    configure_page(title, icon)
    render_sidebar()
    return require_authentication()


def show_connection_status() -> None:
    try:
        from services.supabase_client import get_supabase_client

        get_supabase_client()
        st.success("Supabase bağlantısı aktif.")
    except Exception as exc:
        st.warning(f"Supabase bağlantısı kurulamadı: {exc}")
