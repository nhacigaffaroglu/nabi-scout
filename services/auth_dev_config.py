from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DevAuthConfig:
    enabled: bool
    email: Optional[str]
    password: Optional[str]

    @property
    def is_complete(self) -> bool:
        return bool(
            isinstance(self.email, str)
            and self.email.strip()
            and isinstance(self.password, str)
            and self.password.strip()
        )


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_dev_auth_from_secrets() -> tuple[bool, Optional[str], Optional[str]]:
    try:
        import streamlit as st

        section = st.secrets.get("dev_auth")
        if not section:
            return False, None, None
        enabled = _truthy(str(section.get("enabled") or ""))
        email = str(section.get("email") or "").strip() or None
        password = str(section.get("password") or "").strip() or None
        return enabled, email, password
    except Exception:
        return False, None, None


def load_dev_auth_config() -> DevAuthConfig:
    """Load local development auto-login settings from env or Streamlit secrets."""
    secrets_enabled, secrets_email, secrets_password = _load_dev_auth_from_secrets()
    env_enabled = _truthy(os.environ.get("NABI_DEV_AUTO_LOGIN"))
    enabled = env_enabled or secrets_enabled
    email = (os.environ.get("NABI_DEV_USER_EMAIL") or "").strip() or secrets_email
    password = (os.environ.get("NABI_DEV_USER_PASSWORD") or "").strip() or secrets_password
    return DevAuthConfig(
        enabled=enabled,
        email=email,
        password=password,
    )


def is_dev_auto_login_enabled() -> bool:
    return load_dev_auth_config().enabled
