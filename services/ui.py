import streamlit as st
from supabase import Client

from services.auth_dev_config import is_dev_auto_login_enabled
from services.auth_service import is_authenticated, sign_out


def configure_page(title: str, icon: str) -> None:
    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.title("NABI Scout")
        st.caption("Investment Intelligence")
        st.divider()
        st.caption("Research Platform")
        st.write("Wealth OS verilerini değiştirmez.")
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
