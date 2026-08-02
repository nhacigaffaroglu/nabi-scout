import streamlit as st


def configure_page(title: str, icon: str) -> None:
    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )


def sidebar_navigation() -> None:
    with st.sidebar:
        st.title("NABI Scout")
        st.caption("Investment Intelligence")
        st.divider()
        st.write("Bağımsız araştırma platformu")
        st.write("Wealth OS verilerini değiştirmez.")


def show_connection_status() -> None:
    try:
        from services.supabase_client import get_supabase_client

        get_supabase_client()
        st.success("Supabase yapılandırması bulundu.")
    except Exception as exc:
        st.warning(f"Supabase bağlantısı henüz kurulmadı: {exc}")
