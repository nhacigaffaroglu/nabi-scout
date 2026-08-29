"""Feature flag and conservative bounds for Signal ingestion orchestration.

SEC is the only live adapter in this sprint. KAP remains credential-blocked.
Default is OFF. Missing / None / False never enables ingestion.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from services.hybrid_exposure_allocation_policy import explicit_flag_is_enabled

ENABLE_SEC_SIGNAL_INGESTION_ENV = "NABI_ENABLE_SEC_SIGNAL_INGESTION"
ENABLE_SEC_SIGNAL_INGESTION_VAR = "ENABLE_SEC_SIGNAL_INGESTION"

DEFAULT_MAX_SYMBOLS_PER_RUN = 20
DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_MAX_FILINGS_PER_SYMBOL = 20
DEFAULT_SLEEP_SECONDS = 0.2

STATUS_SUCCESS = "SUCCESS"
STATUS_NO_NEW_EVENTS = "NO_NEW_EVENTS"
STATUS_SKIPPED = "SKIPPED"
STATUS_FAILED = "FAILED"
STATUS_DEFERRED = "DEFERRED"

ADAPTER_SEC = "sec"
ADAPTER_KAP = "kap"


def resolve_sec_signal_ingestion_enabled(
    enable_sec_signal_ingestion: Optional[bool] = None,
) -> bool:
    """Missing / None / False → OFF. Env must be an explicit truthy value."""
    if enable_sec_signal_ingestion is True:
        return True
    if enable_sec_signal_ingestion is False:
        return False
    env = (
        os.environ.get(ENABLE_SEC_SIGNAL_INGESTION_ENV)
        or os.environ.get(ENABLE_SEC_SIGNAL_INGESTION_VAR)
        or ""
    )
    return explicit_flag_is_enabled(env) if env else False


def classify_symbol_status(
    *,
    error: Optional[str],
    event_writes: int,
    evidence_writes: int,
) -> str:
    text = str(error or "").strip().lower()
    if text:
        if "missing cik" in text:
            return STATUS_SKIPPED
        return STATUS_FAILED
    if int(event_writes) > 0 or int(evidence_writes) > 0:
        return STATUS_SUCCESS
    return STATUS_NO_NEW_EVENTS


def env_flag_value(value: Any) -> bool:
    return explicit_flag_is_enabled(value)
