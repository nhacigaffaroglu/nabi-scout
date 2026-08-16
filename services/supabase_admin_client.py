from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from supabase import Client, create_client

from services.auth_dev_config import DevAuthConfig, load_dev_auth_config
from services.supabase_client_factory import (
    SupabaseConfigError,
    _is_valid_supabase_url,
    _normalize_supabase_url,
)

RLS_ADMIN_REQUIRED_MESSAGE = (
    "Universe expansion seed requires an authenticated admin/service client; "
    "publishable key cannot bypass RLS. "
    "Set SUPABASE_SERVICE_ROLE_KEY for headless jobs, or enable [dev_auth] in "
    ".streamlit/secrets.toml (or NABI_DEV_* env vars) for local admin scripts."
)


class SupabaseAdminClientError(SupabaseConfigError):
    """Admin/headless Supabase client could not be created with write access."""


def is_publishable_supabase_key(key: str) -> bool:
    normalized = str(key or "").strip()
    return normalized.startswith("sb_publishable_")


def is_rls_permission_error(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    if code is None and getattr(exc, "args", None):
        code = getattr(exc.args[0], "code", None)
    if str(code) == "42501":
        return True
    message = str(exc).lower()
    return "row-level security" in message or "42501" in message


def raise_friendly_rls_error(exc: BaseException) -> None:
    if is_rls_permission_error(exc):
        raise SupabaseAdminClientError(RLS_ADMIN_REQUIRED_MESSAGE) from exc
    raise exc


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_local_secrets_toml() -> dict:
    secrets_path = _project_root() / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return {}
    try:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]
        return tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def apply_local_secrets_to_env() -> None:
    """Populate script env vars from `.streamlit/secrets.toml` when unset."""
    secrets = load_local_secrets_toml()
    if not secrets:
        return

    def _set(name: str, value: str) -> None:
        if value and not os.environ.get(name):
            os.environ[name] = value

    supabase = secrets.get("supabase") or {}
    fmp = secrets.get("fmp") or {}
    sec = secrets.get("sec") or {}

    _set("SUPABASE_URL", str(supabase.get("url") or "").strip())
    _set(
        "SUPABASE_PUBLISHABLE_KEY",
        str(supabase.get("publishable_key") or "").strip(),
    )
    _set("FMP_API_KEY", str(fmp.get("api_key") or "").strip())
    _set("SEC_CONTACT_EMAIL", str(sec.get("contact_email") or "").strip())

    wealth = secrets.get("wealth_adviser") or {}
    adviser_key = str(wealth.get("api_key") or wealth.get("llm_api_key") or "").strip()
    if adviser_key:
        _set("WEALTH_ADVISER_LLM_API_KEY", adviser_key)
        _set("WEALTH_ADVISER_LLM_ENABLED", "true")
    _set("WEALTH_ADVISER_LLM_MODEL", str(wealth.get("model") or "").strip())
    _set("WEALTH_ADVISER_LLM_PROVIDER", str(wealth.get("provider") or "openai").strip())
    _set(
        "WEALTH_ADVISER_LLM_MAX_OUTPUT_TOKENS",
        str(wealth.get("max_output_tokens") or "").strip(),
    )
    _set(
        "WEALTH_ADVISER_LLM_TIMEOUT_SECONDS",
        str(wealth.get("timeout") or wealth.get("timeout_seconds") or "").strip(),
    )


def _dev_auth_from_secrets(secrets: Mapping[str, object]) -> DevAuthConfig:
    section = secrets.get("dev_auth")
    if not isinstance(section, Mapping):
        return DevAuthConfig(enabled=False, email=None, password=None)
    enabled = str(section.get("enabled") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    email = str(section.get("email") or "").strip() or None
    password = str(section.get("password") or "").strip() or None
    return DevAuthConfig(enabled=enabled, email=email, password=password)


def _resolve_dev_auth_config(secrets: Mapping[str, object]) -> DevAuthConfig:
    env_config = load_dev_auth_config()
    file_config = _dev_auth_from_secrets(secrets)
    enabled = env_config.enabled or file_config.enabled
    email = env_config.email or file_config.email
    password = env_config.password or file_config.password
    return DevAuthConfig(enabled=enabled, email=email, password=password)


def _resolve_supabase_url() -> str:
    secrets = load_local_secrets_toml()
    supabase = secrets.get("supabase") if isinstance(secrets.get("supabase"), dict) else {}
    url = _normalize_supabase_url(
        os.environ.get("SUPABASE_URL")
        or str(supabase.get("url") or "")
    )
    if not url or not _is_valid_supabase_url(url):
        raise SupabaseAdminClientError(
            "SUPABASE_URL is missing or invalid. Set it in the environment or "
            "[supabase].url in .streamlit/secrets.toml."
        )
    return url


def _resolve_publishable_key(secrets: Mapping[str, object]) -> str:
    supabase = secrets.get("supabase") if isinstance(secrets.get("supabase"), dict) else {}
    candidates = (
        os.environ.get("SUPABASE_PUBLISHABLE_KEY"),
        os.environ.get("SUPABASE_KEY"),
        str(supabase.get("publishable_key") or ""),
    )
    for candidate in candidates:
        key = str(candidate or "").strip()
        if key and is_publishable_supabase_key(key):
            return key
    return ""


def _resolve_service_role_key() -> str:
    for env_name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        key = str(os.environ.get(env_name) or "").strip()
        if key and not is_publishable_supabase_key(key):
            return key
    return ""


def _sign_in_publishable_client(client: Client, config: DevAuthConfig) -> Client:
    if not config.enabled or not config.is_complete:
        raise SupabaseAdminClientError(RLS_ADMIN_REQUIRED_MESSAGE)
    try:
        response = client.auth.sign_in_with_password(
            {"email": config.email or "", "password": config.password or ""},
        )
    except Exception as exc:
        raise SupabaseAdminClientError(
            "Supabase dev admin sign-in failed. Check [dev_auth] in "
            ".streamlit/secrets.toml or NABI_DEV_* environment variables."
        ) from exc
    session = getattr(response, "session", None)
    access_token = getattr(session, "access_token", None)
    if not access_token:
        raise SupabaseAdminClientError(
            "Supabase dev admin sign-in did not return a session."
        )
    client.postgrest.auth(access_token)
    return client


def create_admin_supabase_client(
    *,
    url: Optional[str] = None,
    service_role_key: Optional[str] = None,
    publishable_key: Optional[str] = None,
) -> Client:
    """Create a Supabase client suitable for headless/admin writes under RLS."""
    resolved_url = _normalize_supabase_url(url or _resolve_supabase_url())
    if not _is_valid_supabase_url(resolved_url):
        raise SupabaseAdminClientError("SUPABASE_URL is invalid.")

    resolved_service_key = (service_role_key or _resolve_service_role_key()).strip()
    if resolved_service_key:
        return create_client(resolved_url, resolved_service_key)

    secrets = load_local_secrets_toml()
    resolved_publishable = (publishable_key or _resolve_publishable_key(secrets)).strip()
    if not resolved_publishable:
        raise SupabaseAdminClientError(RLS_ADMIN_REQUIRED_MESSAGE)

    client = create_client(resolved_url, resolved_publishable)
    return _sign_in_publishable_client(client, _resolve_dev_auth_config(secrets))
