import streamlit as st
from supabase import Client, create_client


@st.cache_resource
def get_supabase_client() -> Client:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["publishable_key"]
    except KeyError as exc:
        raise RuntimeError(
            "Supabase secrets bulunamadı. Streamlit Secrets alanına "
            "[supabase] url ve publishable_key ekleyin."
        ) from exc

    return create_client(url, key)
