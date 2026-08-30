"""KAP REST configuration placeholders. No default URL. No fake credentials."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional


KAP_BASE_URL_ENV = "NABI_KAP_BASE_URL"
KAP_API_KEY_ENV = "NABI_KAP_API_KEY"
KAP_SERVICE_PATHS_ENV = "NABI_KAP_SERVICE_PATHS"


def _text(raw: Any) -> str:
    return str(raw or "").strip()


def _service_paths_from_env(raw: str) -> dict[str, str]:
    text = _text(raw)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, Mapping):
        return {}
    paths: dict[str, str] = {}
    for key, value in payload.items():
        name = _text(key)
        path = _text(value)
        if name and path:
            paths[name] = path
    return paths


@dataclass(frozen=True)
class KapRestConfig:
    base_url: str = ""
    api_key: str = ""
    service_paths: Optional[dict[str, str]] = None

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.api_key)

    def path_for(self, service: str) -> Optional[str]:
        paths = self.service_paths or {}
        return paths.get(service) or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url_configured": bool(self.base_url),
            "api_key_configured": bool(self.api_key),
            "available": self.available,
            "service_paths_configured": tuple(sorted((self.service_paths or {}).keys())),
        }


def load_kap_rest_config(
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> KapRestConfig:
    env = environ if environ is not None else os.environ
    return KapRestConfig(
        base_url=_text(env.get(KAP_BASE_URL_ENV)),
        api_key=_text(env.get(KAP_API_KEY_ENV)),
        service_paths=_service_paths_from_env(env.get(KAP_SERVICE_PATHS_ENV, "")),
    )
