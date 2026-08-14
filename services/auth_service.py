from __future__ import annotations

import streamlit as st
from supabase import Client

from services.auth_dev_config import is_dev_auto_login_enabled, load_dev_auth_config
from services.supabase_client import (
    AuthenticationRequired,
    get_supabase_client,
    get_supabase_client_for_auth,
)

SESSION_ACCESS_TOKEN_KEY = "nabi_auth_access_token"
SESSION_REFRESH_TOKEN_KEY = "nabi_auth_refresh_token"
SESSION_USER_EMAIL_KEY = "nabi_auth_user_email"

AUTH_FAILURE_MESSAGE = (
    "Kimlik doğrulama başarısız. Oturumunuz sonlandırıldı; lütfen yeniden giriş yapın."
)
LOGIN_FAILURE_MESSAGE = "Giriş başarısız. E-posta veya parola hatalı."
DEV_AUTH_CONFIG_MESSAGE = (
    "Geliştirme oturumu yapılandırılamadı. "
    "NABI_DEV_AUTO_LOGIN / NABI_DEV_USER_EMAIL / NABI_DEV_USER_PASSWORD "
    "veya .streamlit/secrets.toml [dev_auth] ayarlarını kontrol edin."
)


def is_authenticated() -> bool:
    access_token = st.session_state.get(SESSION_ACCESS_TOKEN_KEY)
    refresh_token = st.session_state.get(SESSION_REFRESH_TOKEN_KEY)
    return bool(
        isinstance(access_token, str)
        and access_token.strip()
        and isinstance(refresh_token, str)
        and refresh_token.strip()
    )


def clear_auth_session() -> None:
    from services.wealth_adviser_conversation import clear_adviser_session_state

    for key in (
        SESSION_ACCESS_TOKEN_KEY,
        SESSION_REFRESH_TOKEN_KEY,
        SESSION_USER_EMAIL_KEY,
    ):
        st.session_state.pop(key, None)
    clear_adviser_session_state(st.session_state)


def _store_auth_session(session: object, email: str) -> None:
    access_token = getattr(session, "access_token", None)
    refresh_token = getattr(session, "refresh_token", None)
    if not access_token or not refresh_token:
        raise AuthenticationRequired("Supabase oturumu oluşturulamadı.")
    st.session_state[SESSION_ACCESS_TOKEN_KEY] = access_token
    st.session_state[SESSION_REFRESH_TOKEN_KEY] = refresh_token
    st.session_state[SESSION_USER_EMAIL_KEY] = email.strip()


def apply_session_to_client(client: Client) -> None:
    if not is_authenticated():
        raise AuthenticationRequired("Oturum gerekli.")
    access_token = st.session_state[SESSION_ACCESS_TOKEN_KEY]
    refresh_token = st.session_state[SESSION_REFRESH_TOKEN_KEY]
    client.auth.set_session(access_token, refresh_token)


def _validate_restored_session(client: Client) -> bool:
    try:
        apply_session_to_client(client)
        response = client.auth.get_user()
        user = getattr(response, "user", None)
        return user is not None
    except Exception:
        return False


def sign_in_with_password(email: str, password: str) -> None:
    client = get_supabase_client_for_auth()
    response = client.auth.sign_in_with_password(
        {"email": email.strip(), "password": password},
    )
    session = getattr(response, "session", None)
    if session is None:
        raise AuthenticationRequired(LOGIN_FAILURE_MESSAGE)
    _store_auth_session(session, email)


def _try_dev_auto_login() -> None:
    """Sign in using dev credentials when local auto-login is enabled."""
    config = load_dev_auth_config()
    if not config.enabled:
        return
    if not config.is_complete:
        st.error(f"{DEV_AUTH_CONFIG_MESSAGE} E-posta ve parola gerekli.")
        st.stop()
    try:
        sign_in_with_password(config.email or "", config.password or "")
    except Exception:
        st.error(f"{DEV_AUTH_CONFIG_MESSAGE} Supabase girişi başarısız.")
        st.stop()


def sign_out() -> None:
    if is_authenticated():
        try:
            client = get_supabase_client_for_auth()
            apply_session_to_client(client)
            client.auth.sign_out()
        except Exception:
            pass
    clear_auth_session()


def get_current_user_id(client: Client) -> str:
    """Return authenticated Supabase user id for user-scoped Wealth data."""
    response = client.auth.get_user()
    user = getattr(response, "user", None)
    user_id = getattr(user, "id", None) if user is not None else None
    if not user_id:
        raise AuthenticationRequired("Oturum gerekli.")
    return str(user_id)


def require_authentication() -> Client:
    """Render login when needed; return authenticated Supabase client or stop."""
    if not is_authenticated():
        _try_dev_auto_login()
    if is_authenticated():
        client = get_supabase_client()
        if _validate_restored_session(client):
            return client
        clear_auth_session()
        st.error(AUTH_FAILURE_MESSAGE)
        st.stop()

    st.title("🔐 NABI Scout — Giriş")
    st.caption("Araştırma verilerine erişmek için giriş yapın.")

    with st.form("nabi_auth_login", clear_on_submit=False):
        email = st.text_input("E-posta")
        password = st.text_input("Parola", type="password")
        submitted = st.form_submit_button("Giriş yap", type="primary")

    if submitted:
        if not email.strip() or not password:
            st.error("E-posta ve parola gerekli.")
            st.stop()
        try:
            sign_in_with_password(email, password)
            st.rerun()
        except Exception:
            st.error(LOGIN_FAILURE_MESSAGE)
            st.stop()

    st.stop()
    raise AuthenticationRequired("Oturum gerekli.")
