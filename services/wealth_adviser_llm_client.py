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
    _COMPLETION_TOKEN_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")

    def __init__(self, config: AdviserLlmConfig) -> None:
        self.config = config

    @classmethod
    def _normalized_model_name(cls, model: str) -> str:
        return model.strip().lower().removeprefix("openai/")

    @classmethod
    def uses_max_completion_tokens(cls, model: str) -> bool:
        name = cls._normalized_model_name(model)
        return any(name.startswith(prefix) for prefix in cls._COMPLETION_TOKEN_MODEL_PREFIXES)

    @classmethod
    def supports_temperature(cls, model: str) -> bool:
        return not cls.uses_max_completion_tokens(model)

    @classmethod
    def effective_max_output_tokens(cls, model: str, configured: int) -> int:
        """Reasoning models may consume the full completion budget before content."""
        minimum = 2400 if cls.uses_max_completion_tokens(model) else configured
        return max(minimum, configured)

    def build_chat_completion_body(
        self,
        messages: List[Dict[str, str]],
        *,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if self.uses_max_completion_tokens(self.config.model):
            # GPT-5 family can spend the entire completion budget on reasoning
            # tokens and return empty message.content unless effort is reduced.
            body["reasoning_effort"] = "minimal"
        if self.supports_temperature(self.config.model):
            body["temperature"] = self.config.temperature
        token_param = (
            "max_completion_tokens"
            if self.uses_max_completion_tokens(self.config.model)
            else "max_tokens"
        )
        configured = max_output_tokens or self.config.max_output_tokens
        body[token_param] = self.effective_max_output_tokens(self.config.model, configured)
        return body

    @staticmethod
    def extract_completion_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "finish_reason": None,
            "content_length": 0,
            "reasoning_tokens": None,
            "completion_tokens": None,
            "message_keys": (),
        }
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return metadata
        choice = choices[0] if isinstance(choices[0], dict) else {}
        metadata["finish_reason"] = choice.get("finish_reason")
        message = choice.get("message")
        if isinstance(message, dict):
            metadata["message_keys"] = tuple(sorted(message.keys()))
            content = message.get("content")
            if isinstance(content, str):
                metadata["content_length"] = len(content.strip())
        usage = payload.get("usage")
        if isinstance(usage, dict):
            metadata["completion_tokens"] = usage.get("completion_tokens")
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict):
                metadata["reasoning_tokens"] = details.get("reasoning_tokens")
        return metadata

    @staticmethod
    def parse_provider_error_metadata(response: requests.Response) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "http_status": response.status_code,
            "provider_error_code": None,
            "provider_error_type": None,
        }
        try:
            payload = response.json()
        except ValueError:
            return metadata
        if not isinstance(payload, dict):
            return metadata
        error = payload.get("error")
        if isinstance(error, dict):
            metadata["provider_error_code"] = error.get("code")
            metadata["provider_error_type"] = error.get("type")
        return metadata

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
        token_budget = self.effective_max_output_tokens(
            self.config.model,
            self.config.max_output_tokens,
        )
        max_budget = 4000
        for attempt in range(2):
            body = self.build_chat_completion_body(messages, max_output_tokens=token_budget)
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

            if isinstance(content, str) and content.strip():
                return content.strip()

            metadata = self.extract_completion_metadata(payload)
            if (
                attempt == 0
                and self.uses_max_completion_tokens(self.config.model)
                and metadata.get("finish_reason") == "length"
                and token_budget < max_budget
            ):
                token_budget = min(max(token_budget * 2, 4000), max_budget)
                continue
            break

        raise WealthAdviserLlmError(
            "Adviser LLM returned empty content.",
            error_class="parse",
        )

    @classmethod
    def from_config(cls, config: AdviserLlmConfig) -> "WealthAdviserLlmClient":
        return cls(config)
