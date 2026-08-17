from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from services.bist_symbol_mapping import (
    BIST_PORTFOLIO_SYMBOLS,
    US_MARKETS,
    resolve_bist_provider_symbol,
)
from services.candidate_identity import (
    numeric_current_price,
    select_canonical_candidate,
)
from services.wealth_contract import ASSET_CLASS_EQUITY, normalize_symbol
from services.wealth_price_service import normalize_currency


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
            "failure_reason": None,
            "provider_symbol": None,
            "current_price": numeric_current_price(canonical),
            "market": (canonical or {}).get("market"),
            "currency": (canonical or {}).get("currency"),
            "company_name": (canonical or {}).get("company_name"),
            "duplicate_count": max(0, len(existing) - 1),
        }

    mapping = resolve_bist_provider_symbol(fmp_client, sym)
    fmp_calls = 1  # search-symbol
    if mapping is None:
        return {
            "symbol": sym,
            "status": "unmapped",
            "persisted": False,
            "fmp_calls": fmp_calls,
            "failure_reason": "no_try_istanbul_fmp_search_match",
            "provider_symbol": None,
            "current_price": None,
            "market": None,
            "currency": None,
            "duplicate_count": max(0, len(existing) - 1),
        }

    provider_symbol = mapping["provider_symbol"]
    quote: Dict[str, Any] = {}
    quote_error = None
    try:
        quote = fmp_client.quote(provider_symbol) or {}
        fmp_calls += 1
    except Exception as exc:
        quote_error = str(exc)
        fmp_calls += 1

    quote_currency = normalize_currency(quote.get("currency") or mapping["currency"])
    quote_exchange = str(quote.get("exchange") or mapping["exchange"]).strip().upper()
    price = numeric_current_price({"current_price": quote.get("price")})
    if price is None:
        return {
            "symbol": sym,
            "status": "no_price",
            "persisted": False,
            "fmp_calls": fmp_calls,
            "failure_reason": quote_error or "fmp_quote_plan_restricted_or_empty",
            "provider_symbol": provider_symbol,
            "company_name": mapping["company_name"],
            "current_price": None,
            "market": "TR",
            "currency": mapping["currency"],
            "duplicate_count": max(0, len(existing) - 1),
        }

    if quote_currency != "TRY" or quote_exchange in US_MARKETS:
        return {
            "symbol": sym,
            "status": "rejected_identity",
            "persisted": False,
            "fmp_calls": fmp_calls,
            "failure_reason": "quote_not_try_bist",
            "provider_symbol": provider_symbol,
            "current_price": None,
            "market": None,
            "currency": quote_currency,
            "duplicate_count": max(0, len(existing) - 1),
        }

    payload = {
        "symbol": sym,
        "company_name": (
            quote.get("name")
            or mapping["company_name"]
            or sym
        ),
        "asset_type": "Hisse",
        "market": "TR",
        "currency": "TRY",
        "country": "TR",
        "exchange_name": mapping["exchange"] or "IST",
        "current_price": price,
        "data_source": "FMP",
        "source_updated_at": datetime.now(timezone.utc).isoformat(),
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
        "failure_reason": None,
        "provider_symbol": provider_symbol,
        "company_name": (saved or {}).get("company_name") or payload["company_name"],
        "current_price": numeric_current_price(saved) or price,
        "market": (saved or {}).get("market") or "TR",
        "currency": (saved or {}).get("currency") or "TRY",
        "asset_class": ASSET_CLASS_EQUITY,
        "duplicate_count": max(0, len(after_rows) - 1),
        "candidate_id": (saved or {}).get("id"),
    }


def onboard_bist_symbols(
    symbols: List[str],
    *,
    fmp_client,
    candidate_repo,
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
                    "failure_reason": "not_a_configured_bist_holding",
                }
            )
            continue
        results.append(
            onboard_bist_symbol(
                sym,
                fmp_client=fmp_client,
                candidate_repo=candidate_repo,
            )
        )
    return results
