import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def get_supabase_client() -> Client:
    url = str(st.secrets["supabase"]["url"]).strip()
    key = str(st.secrets["supabase"]["publishable_key"]).strip()
    if not url.startswith("https://") or not url.endswith(".supabase.co"):
        raise RuntimeError("Supabase Project URL geçersiz.")
    if not key.startswith("sb_publishable_"):
        raise RuntimeError("Publishable key geçersiz.")
    return create_client(url, key)
