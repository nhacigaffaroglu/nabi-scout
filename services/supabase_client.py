import streamlit as st
from supabase import Client, create_client


class AuthenticationRequired(RuntimeError):
    """Raised when a Supabase client is requested without an authenticated session."""


def _create_supabase_client() -> Client:
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


def get_supabase_client_for_auth() -> Client:
    """Publishable-key client for sign-in/out only."""
    return _create_supabase_client()


def get_supabase_client() -> Client:
    from services.auth_service import apply_session_to_client, is_authenticated

    if not is_authenticated():
        raise AuthenticationRequired("Oturum gerekli.")
    client = _create_supabase_client()
    apply_session_to_client(client)
    return client
