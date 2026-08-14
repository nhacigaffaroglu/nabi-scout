from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AdviserLlmConfig:
    enabled: bool
    provider: str
    model: str
    timeout_seconds: int
    max_output_tokens: int
    temperature: float
    api_key: Optional[str]

    @property
    def is_usable(self) -> bool:
        return self.enabled and bool(self.api_key)

    def redacted_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "api_key_configured": bool(self.api_key),
        }


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _clamp_int(value: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: str, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _load_secret_string(field_name: str) -> Optional[str]:
    try:
        import streamlit as st

        section = st.secrets.get("wealth_adviser")
        if not section:
            return None
        value = str(section.get(field_name) or "").strip()
        return value or None
    except Exception:
        return None


def _load_api_key_from_secrets() -> Optional[str]:
    return _load_secret_string("api_key") or _load_secret_string("llm_api_key")


def load_adviser_llm_config() -> AdviserLlmConfig:
    api_key = (os.environ.get("WEALTH_ADVISER_LLM_API_KEY") or "").strip() or _load_api_key_from_secrets()
    enabled = _truthy(os.environ.get("WEALTH_ADVISER_LLM_ENABLED")) and bool(api_key)
    provider = (os.environ.get("WEALTH_ADVISER_LLM_PROVIDER") or "openai").strip().lower()
    if provider not in {"openai"}:
        enabled = False
    return AdviserLlmConfig(
        enabled=enabled,
        provider=provider,
        model=(os.environ.get("WEALTH_ADVISER_LLM_MODEL") or _load_secret_string("model") or "gpt-4o-mini").strip(),
        timeout_seconds=_clamp_int(
            os.environ.get("WEALTH_ADVISER_LLM_TIMEOUT_SECONDS") or "30",
            default=30,
            minimum=5,
            maximum=120,
        ),
        max_output_tokens=_clamp_int(
            os.environ.get("WEALTH_ADVISER_LLM_MAX_OUTPUT_TOKENS") or "1200",
            default=1200,
            minimum=256,
            maximum=4000,
        ),
        temperature=_clamp_float(
            os.environ.get("WEALTH_ADVISER_LLM_TEMPERATURE") or "0.2",
            default=0.2,
            minimum=0.0,
            maximum=1.0,
        ),
        api_key=api_key or None,
    )
