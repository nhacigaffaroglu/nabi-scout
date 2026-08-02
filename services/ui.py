import streamlit as st


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
        st.write("Candidate Intelligence v0.3")
        st.write("Wealth OS verilerini değiştirmez.")


def show_connection_status() -> None:
    try:
        from services.supabase_client import get_supabase_client

        get_supabase_client()
        st.success("Supabase bağlantısı aktif.")
    except Exception as exc:
        st.warning(f"Supabase bağlantısı kurulamadı: {exc}")
