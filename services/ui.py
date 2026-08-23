import streamlit as st
from supabase import Client

from services.auth_dev_config import is_dev_auto_login_enabled
from services.auth_service import is_authenticated, sign_out
from components.nabi_design_system import inject_nabi_theme


HIDDEN_NAV_PAGE_HREFS = ("Aday_Detayi",)


def hide_retired_streamlit_pages() -> None:
    """Hide dead pages from Streamlit's auto-generated sidebar nav."""
    selectors = ", ".join(
        f'[data-testid="stSidebarNav"] li:has(a[href*="{href}"])'
        for href in HIDDEN_NAV_PAGE_HREFS
    )
    st.markdown(
        f"<style>{selectors} {{ display: none !important; }}</style>",
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
        st.markdown("**Ana Sayfa**")
        st.page_link("pages/1_Dashboard.py", label="NABI — Bugün", icon="📊")
        st.markdown("**Araştır**")
        st.page_link("pages/2_Aday_Havuzu.py", label="Aday Havuzu", icon="🎯")
        st.page_link("pages/2_Evren_Motoru.py", label="Evren Motoru", icon="🌌")
        st.page_link("pages/2_Scout_Tarama.py", label="Scout Tarama", icon="🔭")
        st.page_link("pages/3_Research_Monitor.py", label="Araştırma Monitörü", icon="🔬")
        st.page_link("pages/4_Company_Report.py", label="Company Report", icon="📄")
        st.page_link("pages/6_Izleme_Listesi.py", label="İzleme Listesi", icon="⭐")
        st.markdown("**Portföy**")
        st.page_link("pages/11_Portfolio_Intelligence.py", label="Portföy Zekâsı", icon="💼")
        st.page_link("pages/10_Wealth.py", label="Wealth (Danışman)", icon="🏦")
        st.markdown("**Monitör & Kararlar**")
        st.page_link("pages/12_Monitor.py", label="Monitör", icon="📡")
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
