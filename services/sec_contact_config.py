from __future__ import annotations

import os

import streamlit as st


class SECContactConfigError(RuntimeError):
    """Missing SEC contact email configuration."""


def resolve_sec_contact_email(*, allow_empty: bool = False) -> str:
    env_value = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    if env_value:
        return env_value
    try:
        section = st.secrets["sec"]
        secret_value = str(section["contact_email"]).strip()
        if secret_value:
            return secret_value
    except (KeyError, AttributeError, TypeError):
        pass
    if allow_empty:
        return ""
    raise SECContactConfigError(
        "SEC contact email gerekli. SEC_CONTACT_EMAIL ortam değişkenini veya "
        "Streamlit Secrets içinde [sec] contact_email ayarlayın."
    )


def get_sec_contact_email() -> str:
    return resolve_sec_contact_email(allow_empty=False)
