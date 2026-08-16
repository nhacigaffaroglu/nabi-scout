from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping


@dataclass
class ProviderCallLedger:
    remote_calls: Dict[str, int] = field(default_factory=dict)
    cache_hits: Dict[str, int] = field(default_factory=dict)
    logical_attempts: Dict[str, int] = field(default_factory=dict)

    def record_remote(self, provider: str, operation: str, count: int = 1) -> None:
        key = f"{provider}:{operation}"
        self.remote_calls[key] = self.remote_calls.get(key, 0) + count
        self.logical_attempts[key] = self.logical_attempts.get(key, 0) + count

    def record_cache_hit(self, provider: str, operation: str, count: int = 1) -> None:
        key = f"{provider}:{operation}"
        self.cache_hits[key] = self.cache_hits.get(key, 0) + count
        self.logical_attempts[key] = self.logical_attempts.get(key, 0) + count

    def provider_totals(self) -> Dict[str, int]:
        totals: Dict[str, int] = {}
        for key, count in self.remote_calls.items():
            provider = key.split(":", 1)[0]
            totals[provider] = totals.get(provider, 0) + count
        return totals

    def to_report(self) -> Dict[str, object]:
        return {
            "remote_calls": dict(self.remote_calls),
            "cache_hits": dict(self.cache_hits),
            "logical_attempts": dict(self.logical_attempts),
            "provider_totals": self.provider_totals(),
        }

    def merge(self, other: Mapping[str, int], *, remote: bool) -> None:
        for key, count in other.items():
            if remote:
                provider, _, operation = key.partition(":")
                if operation:
                    self.record_remote(provider, operation, count)
            else:
                provider, _, operation = key.partition(":")
                if operation:
                    self.record_cache_hit(provider, operation, count)
