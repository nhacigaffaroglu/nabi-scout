from __future__ import annotations

import os
from typing import Optional

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
    return normalized.rstrip("/")


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

    if not resolved_url.startswith("https://") or not resolved_url.endswith(".supabase.co"):
        raise SupabaseConfigError("SUPABASE_URL is invalid.")

    return create_client(resolved_url, resolved_key)
