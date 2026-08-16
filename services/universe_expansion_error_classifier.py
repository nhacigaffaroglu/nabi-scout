from __future__ import annotations

from typing import Optional

from services.fmp_client import FMPError
from services.universe_expansion_contract import (
    ERROR_CATEGORY_NETWORK,
    ERROR_CATEGORY_NOT_FOUND,
    ERROR_CATEGORY_PERMANENT,
    ERROR_CATEGORY_PLAN_RESTRICTED,
    ERROR_CATEGORY_RATE_LIMIT,
    ERROR_CATEGORY_TEMPORARY,
    ERROR_CATEGORY_DATA_INSUFFICIENT,
    ERROR_CATEGORY_PROVIDER_ERROR,
)


def classify_fmp_error(exc: Exception) -> str:
    if isinstance(exc, FMPError):
        mapping = {
            "rate_limit": ERROR_CATEGORY_RATE_LIMIT,
            "plan_restricted": ERROR_CATEGORY_PLAN_RESTRICTED,
            "not_found": ERROR_CATEGORY_NOT_FOUND,
            "transient_http": ERROR_CATEGORY_TEMPORARY,
            "auth": ERROR_CATEGORY_PERMANENT,
            "http_error": ERROR_CATEGORY_PROVIDER_ERROR,
        }
        return mapping.get(exc.error_class or "", ERROR_CATEGORY_PROVIDER_ERROR)
    name = exc.__class__.__name__.lower()
    if "timeout" in name or "connection" in name:
        return ERROR_CATEGORY_NETWORK
    return ERROR_CATEGORY_PROVIDER_ERROR


def classify_sec_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "429" in message or "rate" in message:
        return ERROR_CATEGORY_RATE_LIMIT
    if "404" in message or "not found" in message:
        return ERROR_CATEGORY_NOT_FOUND
    name = exc.__class__.__name__.lower()
    if "timeout" in name or "connection" in name:
        return ERROR_CATEGORY_NETWORK
    return ERROR_CATEGORY_PROVIDER_ERROR


def classify_participation_outcome(
    *,
    available: bool,
    error_message: Optional[str],
    participation_status: str,
    sec_available: bool,
) -> Optional[str]:
    if available and participation_status:
        if participation_status == "Kontrol Et" and not sec_available:
            return ERROR_CATEGORY_DATA_INSUFFICIENT
        return None
    if error_message:
        lowered = error_message.lower()
        if "rate" in lowered or "429" in lowered:
            return ERROR_CATEGORY_RATE_LIMIT
        if "plan" in lowered or "403" in lowered:
            return ERROR_CATEGORY_PLAN_RESTRICTED
    return ERROR_CATEGORY_PROVIDER_ERROR
