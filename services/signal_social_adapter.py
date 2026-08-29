"""Social / X discovery adapter.

Social posts are discovery/context only. They never become VERIFIED
because of engagement or author popularity. Confirmation must come from
an independent TIER 1 source; the social evidence row stays TIER 4.

No unofficial scraping. Direct X API access is not configured.
"""

from __future__ import annotations

from typing import Optional

from services.signal_intelligence_contract import (
    EVENT_SOCIAL_SIGNAL,
    RawSignalInput,
    SOURCE_SOCIAL_X,
)
from services.signal_source_registry import SOCIAL_DISCOVERY_ACCOUNTS, resolve_source


class SocialSignalAdapter:
    """Ready interface for future official X/API ingest."""

    available = False
    limitation = (
        "No official X/social API credentials or supported integration "
        "are configured. Unofficial scraping is not permitted."
    )
    source_identity_strategy = (
        "Registered source_id such as x:bugra_kurtoglu. Authority stays "
        "TIER_4_SOCIAL_DISCOVERY regardless of followers or engagement."
    )
    dedup_strategy = (
        "Evidence identity uses platform post id. Event identity uses a "
        "cited authoritative_event_id (SEC/KAP/issuer) when present; "
        "otherwise the canonical fingerprint. Headline is never identity."
    )
    confirmation_path = (
        "Cite the SEC/KAP/issuer event id to join the factual event. "
        "The social evidence row is never upgraded."
    )

    def registered_accounts(self):
        return SOCIAL_DISCOVERY_ACCOUNTS

    def raw_from_post(
        self,
        *,
        symbol: str,
        source_id: str,
        post_id: Optional[str] = None,
        text: Optional[str] = None,
        posted_at: Optional[str] = None,
        url: Optional[str] = None,
        factual_subject: Optional[str] = None,
        event_type: Optional[str] = None,
        authoritative_event_id: Optional[str] = None,
    ) -> RawSignalInput:
        source = resolve_source(source_id, SOURCE_SOCIAL_X)
        if source.source_type != SOURCE_SOCIAL_X:
            raise ValueError("social adapter accepts SOCIAL_X registrations only")
        return RawSignalInput(
            symbol=symbol,
            source_id=source.source_id,
            source_type=SOURCE_SOCIAL_X,
            event_type=event_type or EVENT_SOCIAL_SIGNAL,
            headline=(text or "")[:180] or None,
            description=text,
            factual_subject=factual_subject,
            event_time=posted_at,
            source_url=url,
            external_id=post_id,
            authoritative_event_id=authoritative_event_id,
            raw_reference=f"social:{source.source_id}:{post_id or 'unidentified'}",
        )

    def fetch_official_feed(self, *_args, **_kwargs) -> tuple[RawSignalInput, ...]:
        raise NotImplementedError(self.limitation)
