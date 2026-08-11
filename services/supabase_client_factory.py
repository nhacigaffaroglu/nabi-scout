from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse

from supabase import Client, create_client


class SupabaseConfigError(RuntimeError):
    """Missing or invalid Supabase environment configuration."""


def _normalize_supabase_url(url: str) -> str:
    normalized = url.strip()
    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in "\"'"
    ):
        normalized = normalized[1:-1].strip()
    normalized = normalized.rstrip("/")

    if not normalized.startswith(("http://", "https://")) and ".supabase.co" in normalized:
        normalized = f"https://{normalized.lstrip('/')}"

    parsed = urlparse(normalized)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return normalized


def _is_valid_supabase_url(url: str) -> bool:
    if not url.startswith("https://"):
        return False
    hostname = urlparse(url).hostname or ""
    return hostname.endswith(".supabase.co")


def create_supabase_client(
    *,
    url: Optional[str] = None,
    key: Optional[str] = None,
) -> Client:
    resolved_url = _normalize_supabase_url(
        url or os.environ.get("SUPABASE_URL") or "",
    )
    resolved_key = (key or os.environ.get("SUPABASE_KEY") or "").strip()

    if not resolved_url or not resolved_key:
        raise SupabaseConfigError(
            "SUPABASE_URL and SUPABASE_KEY environment variables are required."
        )

    if not _is_valid_supabase_url(resolved_url):
        raise SupabaseConfigError(
            "SUPABASE_URL is invalid. Use the Supabase Project URL "
            "(https://<project-ref>.supabase.co)."
        )

    return create_client(resolved_url, resolved_key)
