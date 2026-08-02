import streamlit as st

def configure_page(title, icon):
    st.set_page_config(page_title=title, page_icon=icon, layout="wide")

def render_sidebar():
    with st.sidebar:
        st.title("NABI Scout")
        st.caption("Investment Intelligence")
        st.divider()
        st.write("Candidate Manager v0.2")
        st.write("Wealth OS verilerini değiştirmez.")

def show_connection_status():
    try:
        from services.supabase_client import get_supabase_client
        get_supabase_client()
        st.success("Supabase bağlantısı aktif.")
    except Exception as exc:
        st.warning(f"Supabase bağlantısı kurulamadı: {exc}")
