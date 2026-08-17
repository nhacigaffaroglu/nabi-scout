from __future__ import annotations

from typing import Any, Dict, List

from services.candidate_identity import (
    numeric_current_price,
    select_canonical_candidate,
)
from services.collector_engine import CollectorEngine
from services.wealth_asset_classification import resolve_asset_metadata
from services.wealth_contract import ASSET_CLASS_EQUITY, ASSET_CLASS_ETF, normalize_symbol


# User-confirmed portfolio identity: VISN is a NASDAQ equity, not an ETF.
# CollectorEngine otherwise copies FMP `isEtf` into asset_type.
USER_CONFIRMED_EQUITY_ASSET_TYPE = {"VISN": "Hisse"}


def _expected_candidate_asset_type(symbol: str) -> Optional[str]:
    override = USER_CONFIRMED_EQUITY_ASSET_TYPE.get(symbol)
    if override:
        return override
    asset_class, _, _, status = resolve_asset_metadata(symbol, currency="USD")
    if status != "RESOLVED":
        return None
    if asset_class == ASSET_CLASS_ETF:
        return "ETF"
    if asset_class == ASSET_CLASS_EQUITY:
        return "Hisse"
    return None


def onboard_portfolio_symbol(
    symbol: str,
    *,
    collector: CollectorEngine,
    candidate_repo,
) -> Dict[str, Any]:
    """Persist one portfolio symbol via CollectorEngine + canonical reuse.

    Does not insert a row when FMP returns no usable current_price.
    Does not call SEC (no CIK). Skips provider calls when a priced
    canonical candidate already exists.
    """
    sym = normalize_symbol(symbol)
    existing = candidate_repo.list_by_symbol(sym)
    duplicate_count = max(0, len(existing) - 1) if existing else 0
    canonical = select_canonical_candidate(existing)
    if numeric_current_price(canonical) is not None:
        return {
            "symbol": sym,
            "status": "already_priced",
            "persisted": False,
            "fmp_calls": 0,
            "sec_calls": 0,
            "candidate_id": canonical.get("id") if canonical else None,
            "company_name": (canonical or {}).get("company_name"),
            "asset_type": (canonical or {}).get("asset_type"),
            "market": (canonical or {}).get("market"),
            "current_price": numeric_current_price(canonical),
            "duplicate_count": duplicate_count,
            "provider_mismatch": None,
            "failure_reason": None,
        }

    collected = collector.collect(sym)
    fmp_calls = 2  # profile + quote
    candidate = dict(collected.get("candidate") or {})
    provider_asset_type = candidate.get("asset_type")
    expected_type = _expected_candidate_asset_type(sym)
    provider_mismatch = None
    if expected_type and provider_asset_type and provider_asset_type != expected_type:
        provider_mismatch = {
            "field": "asset_type",
            "provider": provider_asset_type,
            "portfolio": expected_type,
        }
        if sym in USER_CONFIRMED_EQUITY_ASSET_TYPE:
            candidate["asset_type"] = expected_type

    price = numeric_current_price(candidate)
    if price is None:
        return {
            "symbol": sym,
            "status": "no_price",
            "persisted": False,
            "fmp_calls": fmp_calls,
            "sec_calls": 0,
            "candidate_id": None,
            "company_name": candidate.get("company_name"),
            "asset_type": candidate.get("asset_type"),
            "market": candidate.get("market"),
            "current_price": None,
            "duplicate_count": duplicate_count,
            "provider_mismatch": provider_mismatch,
            "failure_reason": "collector_returned_no_numeric_current_price",
            "endpoint_status": collected.get("endpoint_status"),
            "errors": collected.get("errors"),
        }

    saved = candidate_repo.upsert_expansion_candidate(candidate)
    after_rows = candidate_repo.list_by_symbol(sym)
    return {
        "symbol": sym,
        "status": "persisted",
        "persisted": True,
        "fmp_calls": fmp_calls,
        "sec_calls": 0,
        "candidate_id": (saved or {}).get("id"),
        "company_name": (saved or {}).get("company_name") or candidate.get("company_name"),
        "asset_type": (saved or {}).get("asset_type") or candidate.get("asset_type"),
        "market": (saved or {}).get("market") or candidate.get("market"),
        "current_price": numeric_current_price(saved) or price,
        "duplicate_count": max(0, len(after_rows) - 1) if after_rows else 0,
        "provider_mismatch": provider_mismatch,
        "failure_reason": None,
    }


def onboard_portfolio_symbols(
    symbols: List[str],
    *,
    collector: CollectorEngine,
    candidate_repo,
) -> List[Dict[str, Any]]:
    return [
        onboard_portfolio_symbol(
            symbol,
            collector=collector,
            candidate_repo=candidate_repo,
        )
        for symbol in symbols
    ]
