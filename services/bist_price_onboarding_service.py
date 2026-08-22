from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from services.bist_symbol_mapping import (
    BIST_PORTFOLIO_SYMBOLS,
    US_MARKETS,
    canonical_bist_provider_mapping,
)
from services.candidate_identity import (
    numeric_current_price,
    select_canonical_candidate,
)
from services.current_market_data import (
    AlphaVantageCurrentMarketData,
    FmpCurrentMarketData,
    TwelveDataCurrentMarketData,
    fetch_equity_quote,
)
from services.current_market_data_contract import PROVIDER_ALPHA_VANTAGE
from services.wealth_contract import ASSET_CLASS_EQUITY, normalize_symbol


def _us_contaminated(rows: List[Dict[str, Any]]) -> bool:
    for row in rows:
        market = str(row.get("market") or "").strip().upper()
        exchange = str(row.get("exchange_name") or row.get("exchange") or "").strip().upper()
        if market in US_MARKETS or exchange in US_MARKETS:
            return True
    return False


def onboard_bist_symbol(
    symbol: str,
    *,
    fmp_client,
    candidate_repo,
    alpha_vantage_client=None,
    twelve_data_client=None,
) -> Dict[str, Any]:
    """Persist a BIST equity price without CollectorEngine ABD routing.

    Does not insert a row when the provider returns no usable price.
    """
    sym = normalize_symbol(symbol)
    existing = candidate_repo.list_by_symbol(sym)
    if _us_contaminated(existing):
        return {
            "symbol": sym,
            "status": "us_contamination",
            "persisted": False,
            "fmp_calls": 0,
            "fallback_calls": 0,
            "failure_reason": "existing_us_or_abd_candidate_for_bist_symbol",
            "provider_symbol": None,
            "current_price": None,
            "market": None,
            "currency": None,
            "duplicate_count": max(0, len(existing) - 1),
        }

    tr_rows = [
        row
        for row in existing
        if str(row.get("market") or "").strip().upper() in {"TR", "BIST", "IST"}
    ]
    canonical = select_canonical_candidate(tr_rows or existing, preferred_market="TR")
    if numeric_current_price(canonical) is not None and not _us_contaminated([canonical] if canonical else []):
        return {
            "symbol": sym,
            "status": "already_priced",
            "persisted": False,
            "fmp_calls": 0,
            "fallback_calls": 0,
            "failure_reason": None,
            "provider_symbol": None,
            "current_price": numeric_current_price(canonical),
            "market": (canonical or {}).get("market"),
            "currency": (canonical or {}).get("currency"),
            "company_name": (canonical or {}).get("company_name"),
            "duplicate_count": max(0, len(existing) - 1),
        }

    mapping = canonical_bist_provider_mapping(sym)
    if mapping is None:
        return {
            "symbol": sym,
            "status": "unmapped",
            "persisted": False,
            "fmp_calls": 0,
            "fallback_calls": 0,
            "failure_reason": "no_try_istanbul_fmp_search_match",
            "provider_symbol": None,
            "current_price": None,
            "market": None,
            "currency": None,
            "duplicate_count": max(0, len(existing) - 1),
        }

    primary = FmpCurrentMarketData(fmp_client)
    fallbacks = []
    if twelve_data_client is not None:
        fallbacks.append(TwelveDataCurrentMarketData(twelve_data_client))
    if alpha_vantage_client is not None:
        fallbacks.append(AlphaVantageCurrentMarketData(alpha_vantage_client))
    result = fetch_equity_quote(
        sym,
        expected_currency="TRY",
        market="TR",
        primary=primary,
        fallbacks=fallbacks,
        skip_provider_names=(PROVIDER_ALPHA_VANTAGE,),
    )
    fmp_calls = primary.calls
    fallback_calls = sum(provider.calls for provider in fallbacks)
    provider_symbol = result.provider_symbol or mapping["provider_symbol"]
    if not result.ok:
        status = (
            "rejected_identity"
            if result.failure_class
            and result.failure_class.value in {"currency_mismatch", "invalid_symbol_mapping"}
            else "no_price"
        )
        return {
            "symbol": sym,
            "status": status,
            "persisted": False,
            "fmp_calls": fmp_calls,
            "fallback_calls": fallback_calls,
            "failure_reason": result.error or "provider_quote_unavailable",
            "provider_symbol": provider_symbol,
            "provider": result.provider,
            "company_name": mapping["company_name"],
            "current_price": None,
            "market": "TR",
            "currency": mapping["currency"],
            "duplicate_count": max(0, len(existing) - 1),
        }

    payload = {
        "symbol": sym,
        "company_name": mapping["company_name"] or sym,
        "asset_type": "Hisse",
        "market": "TR",
        "currency": "TRY",
        "country": "TR",
        "exchange_name": mapping["exchange"] or "IST",
        "current_price": result.price,
        "data_source": result.provider,
        "source_updated_at": result.as_of or result.retrieved_at,
        "collector_notes": f"provider_symbol={provider_symbol}",
        "participation_status": "Kontrol Et",
        "participation_score": 60,
    }
    saved = candidate_repo.upsert_by_symbol(payload)
    after_rows = candidate_repo.list_by_symbol(sym)
    return {
        "symbol": sym,
        "status": "persisted",
        "persisted": True,
        "fmp_calls": fmp_calls,
        "fallback_calls": fallback_calls,
        "failure_reason": None,
        "provider_symbol": provider_symbol,
        "provider": result.provider,
        "company_name": (saved or {}).get("company_name") or payload["company_name"],
        "current_price": numeric_current_price(saved) or result.price,
        "market": (saved or {}).get("market") or "TR",
        "currency": (saved or {}).get("currency") or "TRY",
        "asset_class": ASSET_CLASS_EQUITY,
        "duplicate_count": max(0, len(after_rows) - 1),
        "candidate_id": (saved or {}).get("id"),
    }


def persist_validated_bist_quote(result, candidate_repo) -> Dict[str, Any]:
    """Persist already-validated BIST evidence through the canonical candidate path."""
    if not getattr(result, "ok", False) or result.price is None:
        raise ValueError("validated BIST quote is required")
    sym = normalize_symbol(result.canonical_symbol)
    mapping = canonical_bist_provider_mapping(sym) or {}
    payload = {
        "symbol": sym,
        "company_name": mapping.get("company_name") or sym,
        "asset_type": "Hisse",
        "market": "TR",
        "currency": "TRY",
        "country": "TR",
        "exchange_name": mapping.get("exchange") or "IST",
        "current_price": result.price,
        "data_source": result.provider,
        "source_updated_at": result.as_of or result.retrieved_at,
        "collector_notes": f"provider_symbol={result.provider_symbol}",
        "participation_status": "Kontrol Et",
        "participation_score": 60,
    }
    saved = candidate_repo.upsert_by_symbol(payload)
    after_rows = candidate_repo.list_by_symbol(sym)
    return {
        "symbol": sym,
        "status": "persisted",
        "persisted": True,
        "provider": result.provider,
        "provider_symbol": result.provider_symbol,
        "current_price": numeric_current_price(saved) or result.price,
        "currency": (saved or {}).get("currency") or "TRY",
        "data_source": (saved or {}).get("data_source") or result.provider,
        "source_updated_at": (saved or {}).get("source_updated_at") or payload["source_updated_at"],
        "candidate_id": (saved or {}).get("id"),
        "duplicate_count": max(0, len(after_rows) - 1),
    }


def onboard_bist_symbols(
    symbols: List[str],
    *,
    fmp_client,
    candidate_repo,
    alpha_vantage_client=None,
    twelve_data_client=None,
) -> List[Dict[str, Any]]:
    target = [normalize_symbol(sym) for sym in symbols]
    results = []
    for sym in target:
        if sym not in BIST_PORTFOLIO_SYMBOLS:
            results.append(
                {
                    "symbol": sym,
                    "status": "skipped",
                    "persisted": False,
                    "fmp_calls": 0,
                    "fallback_calls": 0,
                    "failure_reason": "not_a_configured_bist_holding",
                }
            )
            continue
        results.append(
            onboard_bist_symbol(
                sym,
                fmp_client=fmp_client,
                candidate_repo=candidate_repo,
                alpha_vantage_client=alpha_vantage_client,
                twelve_data_client=twelve_data_client,
            )
        )
    return results
