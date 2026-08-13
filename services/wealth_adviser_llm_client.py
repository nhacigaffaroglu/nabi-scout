from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

from services.wealth_adviser_config import AdviserLlmConfig


class WealthAdviserLlmError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_class: str = "unknown",
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.status_code = status_code


class WealthAdviserLlmClient:
    """Minimal OpenAI-compatible chat completion client for adviser interpretation."""

    OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, config: AdviserLlmConfig) -> None:
        self.config = config

    def complete(self, messages: List[Dict[str, str]]) -> str:
        if not self.config.is_usable:
            raise WealthAdviserLlmError(
                "Adviser LLM is not configured.",
                error_class="config",
            )
        if self.config.provider != "openai":
            raise WealthAdviserLlmError(
                f"Unsupported adviser LLM provider: {self.config.provider}",
                error_class="config",
            )

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = requests.post(
                self.OPENAI_CHAT_URL,
                headers=headers,
                json=body,
                timeout=self.config.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise WealthAdviserLlmError(
                "Adviser LLM request timed out.",
                error_class="timeout",
            ) from exc
        except requests.RequestException as exc:
            raise WealthAdviserLlmError(
                f"Adviser LLM request failed: {exc}",
                error_class="network",
            ) from exc

        if response.status_code >= 400:
            raise WealthAdviserLlmError(
                f"Adviser LLM HTTP {response.status_code}",
                error_class="provider",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise WealthAdviserLlmError(
                "Adviser LLM returned malformed response.",
                error_class="parse",
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise WealthAdviserLlmError(
                "Adviser LLM returned empty content.",
                error_class="parse",
            )
        return content.strip()

    @classmethod
    def from_config(cls, config: AdviserLlmConfig) -> "WealthAdviserLlmClient":
        return cls(config)
