import streamlit as st
from supabase import Client, create_client


@st.cache_resource
def get_supabase_client() -> Client:
    try:
        url = str(st.secrets["supabase"]["url"]).strip()
        key = str(st.secrets["supabase"]["publishable_key"]).strip()
    except KeyError as exc:
        raise RuntimeError(
            "Supabase secrets bulunamadı. "
            "Streamlit Secrets alanına url ve publishable_key ekleyin."
        ) from exc

    if not url.startswith("https://") or not url.endswith(".supabase.co"):
        raise RuntimeError("Supabase Project URL geçersiz.")

    if not key.startswith("sb_publishable_"):
        raise RuntimeError("Supabase publishable key geçersiz.")

    return create_client(url, key)
