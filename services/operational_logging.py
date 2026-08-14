from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("nabi_scout.ops")


def log_provider_failure(data_family: str, symbol: Optional[str] = None, reason: str = "") -> None:
    logger.warning(
        "provider_failure data_family=%s symbol=%s reason=%s",
        data_family,
        symbol or "-",
        reason or "unknown",
    )


def log_company_intelligence_partial(symbol: str, partial_sections: str) -> None:
    logger.info(
        "company_intelligence_partial symbol=%s sections=%s",
        symbol,
        partial_sections,
    )


def log_thesis_save_dedupe(symbol: str) -> None:
    logger.info("thesis_snapshot_dedupe symbol=%s", symbol)


def log_adviser_fallback(reason_code: str) -> None:
    logger.info("adviser_llm_fallback reason=%s", reason_code)
