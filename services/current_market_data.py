from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol, Sequence

from services.bist_eod_bulletin import BorsaIstanbulThbClient, BistThbDownloadError
from services.bist_symbol_mapping import (
    ALPHA_VANTAGE_BIST_CAPABLE,
    TWELVE_DATA_BIST_EXCHANGES,
    US_MARKETS,
    alpha_vantage_bist_provider_symbol,
    borsa_istanbul_eod_series,
    canonical_bist_provider_mapping,
    twelve_data_bist_request,
)
from services.candidate_identity import numeric_current_price
from services.current_market_data_contract import (
    FALLBACK_ELIGIBLE,
    INTEGRITY_FAILURES,
    PROVIDER_ALPHA_VANTAGE,
    PROVIDER_BORSA_ISTANBUL_EOD,
    PROVIDER_FMP,
    PROVIDER_TWELVE_DATA,
    EquityQuoteResult,
    FxRateResult,
    ProviderFailureClass,
)
from services.fmp_client import FMPError
from services.twelve_data_client import TwelveDataError
from services.wealth_contract import normalize_symbol
from services.wealth_price_service import normalize_currency


class CurrentMarketDataProvider(Protocol):
    name: str
    calls: int

    def get_equity_quote(
        self,
        canonical_symbol: str,
        *,
        expected_currency: str,
        market: str,
    ) -> EquityQuoteResult:
        ...

    def get_fx_rate(self, base_currency: str, quote_currency: str) -> FxRateResult:
        ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _numeric_rate(raw) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value != value:
        return None
    return value


def _fmp_failure_class(exc: FMPError) -> ProviderFailureClass:
    mapping = {
        "plan_restricted": ProviderFailureClass.PLAN_RESTRICTED,
        "not_found": ProviderFailureClass.UNSUPPORTED_SYMBOL,
        "empty": ProviderFailureClass.UNSUPPORTED_SYMBOL,
        "auth": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "rate_limit": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "timeout": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "network": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "transient_http": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "http_error": ProviderFailureClass.ENDPOINT_UNAVAILABLE,
        "unknown": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "malformed": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
    }
    return mapping.get(str(exc.error_class or "").strip().lower(), ProviderFailureClass.PROVIDER_ACCESS_FAILURE)


def _fmp_as_of(quote: dict) -> Optional[str]:
    timestamp = quote.get("timestamp")
    if timestamp is not None and timestamp != "":
        try:
            return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    for key in ("date", "datetime"):
        raw = quote.get(key)
        if raw:
            return str(raw)
    return None


def _equity_fail(
    *,
    canonical_symbol: str,
    provider: str,
    provider_symbol: str,
    failure_class: ProviderFailureClass,
    error: str,
    retrieved_at: Optional[str] = None,
) -> EquityQuoteResult:
    return EquityQuoteResult(
        ok=False,
        canonical_symbol=canonical_symbol,
        provider=provider,
        provider_symbol=provider_symbol,
        price=None,
        currency=None,
        as_of=None,
        retrieved_at=retrieved_at or _now_iso(),
        failure_class=failure_class,
        error=error,
    )


def _fx_fail(
    *,
    base_currency: str,
    quote_currency: str,
    provider: str,
    failure_class: ProviderFailureClass,
    error: str,
    retrieved_at: Optional[str] = None,
) -> FxRateResult:
    return FxRateResult(
        ok=False,
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=None,
        provider=provider,
        as_of=None,
        retrieved_at=retrieved_at or _now_iso(),
        failure_class=failure_class,
        error=error,
    )


class FmpCurrentMarketData:
    name = PROVIDER_FMP

    def __init__(self, client) -> None:
        self._client = client
        self.calls = 0

    def get_equity_quote(
        self,
        canonical_symbol: str,
        *,
        expected_currency: str,
        market: str,
    ) -> EquityQuoteResult:
        retrieved_at = _now_iso()
        canonical = normalize_symbol(canonical_symbol)
        expected = normalize_currency(expected_currency)
        provider_symbol = _fmp_equity_provider_symbol(canonical, market)
        if provider_symbol is None:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol="",
                failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
                error="no_fmp_provider_symbol_for_canonical_asset",
                retrieved_at=retrieved_at,
            )
        self.calls += 1
        try:
            quote = self._client.quote(provider_symbol) or {}
        except FMPError as exc:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=_fmp_failure_class(exc),
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        except Exception as exc:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        if not isinstance(quote, dict):
            quote = {}
        return _validate_equity_quote(
            canonical_symbol=canonical,
            provider=self.name,
            provider_symbol=provider_symbol,
            price_raw=quote.get("price"),
            currency_raw=quote.get("currency"),
            exchange_raw=quote.get("exchange"),
            expected_currency=expected,
            as_of=_fmp_as_of(quote),
            retrieved_at=retrieved_at,
        )

    def get_fx_rate(self, base_currency: str, quote_currency: str) -> FxRateResult:
        base = normalize_currency(base_currency)
        quote = normalize_currency(quote_currency)
        direct = self._quote_fx_symbol(f"{base}{quote}", inverted=False)
        if direct.ok or direct.failure_class in INTEGRITY_FAILURES:
            return _with_pair(direct, base, quote)
        inverse = self._quote_fx_symbol(f"{quote}{base}", inverted=True)
        if inverse.ok:
            inverted_rate = 1.0 / inverse.rate if inverse.rate else None
            if inverted_rate is None:
                return _fx_fail(
                    base_currency=base,
                    quote_currency=quote,
                    provider=self.name,
                    failure_class=ProviderFailureClass.MALFORMED_PRICE,
                    error="fmp_inverse_fx_not_invertible",
                    retrieved_at=inverse.retrieved_at,
                )
            return FxRateResult(
                ok=True,
                base_currency=base,
                quote_currency=quote,
                rate=inverted_rate,
                provider=self.name,
                as_of=inverse.as_of,
                retrieved_at=inverse.retrieved_at,
                inverted=True,
            )
        return _with_pair(direct, base, quote)

    def _quote_fx_symbol(self, symbol: str, *, inverted: bool) -> FxRateResult:
        retrieved_at = _now_iso()
        self.calls += 1
        try:
            payload = self._client.quote(symbol) or {}
        except FMPError as exc:
            return _fx_fail(
                base_currency="",
                quote_currency="",
                provider=self.name,
                failure_class=_fmp_failure_class(exc),
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        except Exception as exc:
            return _fx_fail(
                base_currency="",
                quote_currency="",
                provider=self.name,
                failure_class=ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        if isinstance(payload, list) and payload:
            payload = payload[0]
        if not isinstance(payload, dict):
            payload = {}
        rate = _numeric_rate(payload.get("price"))
        if rate is None:
            return _fx_fail(
                base_currency="",
                quote_currency="",
                provider=self.name,
                failure_class=ProviderFailureClass.UNSUPPORTED_SYMBOL,
                error="fmp_fx_quote_empty",
                retrieved_at=retrieved_at,
            )
        return FxRateResult(
            ok=True,
            base_currency="",
            quote_currency="",
            rate=rate,
            provider=self.name,
            as_of=_fmp_as_of(payload),
            retrieved_at=retrieved_at,
            inverted=inverted,
        )


def _with_pair(result: FxRateResult, base: str, quote: str) -> FxRateResult:
    return FxRateResult(
        ok=result.ok,
        base_currency=base,
        quote_currency=quote,
        rate=result.rate,
        provider=result.provider,
        as_of=result.as_of,
        retrieved_at=result.retrieved_at,
        inverted=result.inverted,
        failure_class=result.failure_class,
        error=result.error,
    )


def _fmp_equity_provider_symbol(canonical: str, market: str) -> Optional[str]:
    market_code = str(market or "").strip().upper()
    if market_code in {"TR", "BIST", "IST", "TURKEY"}:
        mapping = canonical_bist_provider_mapping(canonical)
        if mapping is None:
            return None
        return mapping["provider_symbol"]
    return canonical


def _av_failure_class(exc) -> ProviderFailureClass:
    status = str(getattr(exc, "status", "") or getattr(exc, "error_class", "") or "").upper()
    error_class = str(getattr(exc, "error_class", "") or "").lower()
    if status in {"PREMIUM_REQUIRED"} or error_class in {"premium_required", "unavailable"}:
        return ProviderFailureClass.PLAN_RESTRICTED
    if status in {"NOT_FOUND"} or error_class == "not_found":
        return ProviderFailureClass.UNSUPPORTED_SYMBOL
    if status in {"RATE_LIMIT", "AUTH", "NETWORK"} or error_class in {
        "rate_limit",
        "auth",
        "network",
    }:
        return ProviderFailureClass.PROVIDER_ACCESS_FAILURE
    if error_class == "malformed" or status == "MALFORMED":
        return ProviderFailureClass.PROVIDER_ACCESS_FAILURE
    return ProviderFailureClass.PROVIDER_ACCESS_FAILURE


class AlphaVantageCurrentMarketData:
    name = PROVIDER_ALPHA_VANTAGE

    def __init__(self, client) -> None:
        self._client = client
        self.calls = 0

    def get_equity_quote(
        self,
        canonical_symbol: str,
        *,
        expected_currency: str,
        market: str,
    ) -> EquityQuoteResult:
        retrieved_at = _now_iso()
        canonical = normalize_symbol(canonical_symbol)
        expected = normalize_currency(expected_currency)
        market_code = str(market or "").strip().upper()
        if (
            market_code in {"TR", "BIST", "IST", "TURKEY"}
            and not ALPHA_VANTAGE_BIST_CAPABLE
        ):
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=_av_equity_provider_symbol(canonical, market) or "",
                failure_class=ProviderFailureClass.UNSUPPORTED_SYMBOL,
                error="alpha_vantage_bist_capability_absent",
                retrieved_at=retrieved_at,
            )
        provider_symbol = _av_equity_provider_symbol(canonical, market)
        if provider_symbol is None:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol="",
                failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
                error="no_alpha_vantage_provider_symbol_for_canonical_asset",
                retrieved_at=retrieved_at,
            )
        self.calls += 1
        try:
            quote = self._client.global_quote(provider_symbol) or {}
        except Exception as exc:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=_av_failure_class(exc),
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        if not isinstance(quote, dict):
            quote = {}
        return _validate_equity_quote(
            canonical_symbol=canonical,
            provider=self.name,
            provider_symbol=str(quote.get("01. symbol") or provider_symbol).strip().upper()
            or provider_symbol,
            price_raw=quote.get("05. price"),
            currency_raw=quote.get("currency"),
            exchange_raw=quote.get("exchange"),
            expected_currency=expected,
            as_of=str(quote.get("07. latest trading day") or "").strip() or None,
            retrieved_at=retrieved_at,
        )

    def get_fx_rate(self, base_currency: str, quote_currency: str) -> FxRateResult:
        base = normalize_currency(base_currency)
        quote = normalize_currency(quote_currency)
        direct = self._exchange_rate(from_currency=base, to_currency=quote, invert=False)
        if direct.ok or direct.failure_class in INTEGRITY_FAILURES:
            return direct
        inverse = self._exchange_rate(from_currency=quote, to_currency=base, invert=True)
        if inverse.ok:
            return inverse
        return direct

    def _exchange_rate(
        self,
        *,
        from_currency: str,
        to_currency: str,
        invert: bool,
    ) -> FxRateResult:
        retrieved_at = _now_iso()
        requested_base = to_currency if invert else from_currency
        requested_quote = from_currency if invert else to_currency
        self.calls += 1
        try:
            payload = self._client.currency_exchange_rate(
                from_currency=from_currency,
                to_currency=to_currency,
            ) or {}
        except Exception as exc:
            return _fx_fail(
                base_currency=requested_base if not invert else to_currency,
                quote_currency=requested_quote if not invert else from_currency,
                provider=self.name,
                failure_class=_av_failure_class(exc),
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        if not isinstance(payload, dict):
            payload = {}
        from_code = normalize_currency(payload.get("1. From_Currency Code") or from_currency)
        to_code = normalize_currency(payload.get("3. To_Currency Code") or to_currency)
        rate = _numeric_rate(payload.get("5. Exchange Rate"))
        as_of = str(payload.get("6. Last Refreshed") or "").strip() or None
        canonical_base = to_currency if invert else from_currency
        canonical_quote = from_currency if invert else to_currency
        if from_code == from_currency and to_code == to_currency:
            if rate is None:
                return _fx_fail(
                    base_currency=canonical_base,
                    quote_currency=canonical_quote,
                    provider=self.name,
                    failure_class=ProviderFailureClass.MALFORMED_PRICE,
                    error="alpha_vantage_fx_rate_invalid",
                    retrieved_at=retrieved_at,
                )
            if invert:
                return FxRateResult(
                    ok=True,
                    base_currency=canonical_base,
                    quote_currency=canonical_quote,
                    rate=1.0 / rate,
                    provider=self.name,
                    as_of=as_of,
                    retrieved_at=retrieved_at,
                    inverted=True,
                )
            return FxRateResult(
                ok=True,
                base_currency=canonical_base,
                quote_currency=canonical_quote,
                rate=rate,
                provider=self.name,
                as_of=as_of,
                retrieved_at=retrieved_at,
                inverted=False,
            )
        if from_code == to_currency and to_code == from_currency:
            if rate is None:
                return _fx_fail(
                    base_currency=canonical_base,
                    quote_currency=canonical_quote,
                    provider=self.name,
                    failure_class=ProviderFailureClass.MALFORMED_PRICE,
                    error="alpha_vantage_fx_rate_invalid",
                    retrieved_at=retrieved_at,
                )
            return FxRateResult(
                ok=True,
                base_currency=canonical_base,
                quote_currency=canonical_quote,
                rate=1.0 / rate,
                provider=self.name,
                as_of=as_of,
                retrieved_at=retrieved_at,
                inverted=True,
            )
        return _fx_fail(
            base_currency=canonical_base,
            quote_currency=canonical_quote,
            provider=self.name,
            failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
            error="alpha_vantage_fx_pair_mismatch",
            retrieved_at=retrieved_at,
        )


def _av_equity_provider_symbol(canonical: str, market: str) -> Optional[str]:
    market_code = str(market or "").strip().upper()
    if market_code in {"TR", "BIST", "IST", "TURKEY"}:
        return alpha_vantage_bist_provider_symbol(canonical)
    return canonical


def _validate_equity_quote(
    *,
    canonical_symbol: str,
    provider: str,
    provider_symbol: str,
    price_raw,
    currency_raw,
    exchange_raw,
    expected_currency: str,
    as_of: Optional[str],
    retrieved_at: str,
) -> EquityQuoteResult:
    exchange = str(exchange_raw or "").strip().upper()
    if exchange in US_MARKETS and expected_currency == "TRY":
        return _equity_fail(
            canonical_symbol=canonical_symbol,
            provider=provider,
            provider_symbol=provider_symbol,
            failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
            error="quote_not_try_bist",
            retrieved_at=retrieved_at,
        )
    currency = normalize_currency(currency_raw) if currency_raw else expected_currency
    if currency != expected_currency:
        return _equity_fail(
            canonical_symbol=canonical_symbol,
            provider=provider,
            provider_symbol=provider_symbol,
            failure_class=ProviderFailureClass.CURRENCY_MISMATCH,
            error=f"expected_{expected_currency}_got_{currency}",
            retrieved_at=retrieved_at,
        )
    price = numeric_current_price({"current_price": price_raw})
    if price is None:
        return _equity_fail(
            canonical_symbol=canonical_symbol,
            provider=provider,
            provider_symbol=provider_symbol,
            failure_class=ProviderFailureClass.MALFORMED_PRICE
            if price_raw not in (None, "")
            else ProviderFailureClass.UNSUPPORTED_SYMBOL,
            error="invalid_or_missing_price",
            retrieved_at=retrieved_at,
        )
    return EquityQuoteResult(
        ok=True,
        canonical_symbol=canonical_symbol,
        provider=provider,
        provider_symbol=provider_symbol,
        price=price,
        currency=currency,
        as_of=as_of,
        retrieved_at=retrieved_at,
        exchange=exchange or None,
    )


def _td_failure_class(exc: TwelveDataError) -> ProviderFailureClass:
    mapping = {
        "plan_restricted": ProviderFailureClass.PLAN_RESTRICTED,
        "not_found": ProviderFailureClass.UNSUPPORTED_SYMBOL,
        "auth": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "rate_limit": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "network": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "malformed": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
        "provider_access_failure": ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
    }
    return mapping.get(str(exc.error_class or "").strip().lower(), ProviderFailureClass.PROVIDER_ACCESS_FAILURE)


def _td_as_of(payload: dict) -> Optional[str]:
    timestamp = payload.get("timestamp") or payload.get("last_quote_at")
    if timestamp is not None and timestamp != "":
        try:
            return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    raw = payload.get("datetime")
    return str(raw) if raw else None


def _response_symbol_base(raw: str) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    for sep in (":", ".", "/"):
        if sep in text:
            return text.split(sep, 1)[0]
    return text


class TwelveDataCurrentMarketData:
    name = PROVIDER_TWELVE_DATA

    def __init__(self, client) -> None:
        self._client = client
        self.calls = 0

    def get_equity_quote(
        self,
        canonical_symbol: str,
        *,
        expected_currency: str,
        market: str,
    ) -> EquityQuoteResult:
        retrieved_at = _now_iso()
        canonical = normalize_symbol(canonical_symbol)
        expected = normalize_currency(expected_currency)
        request = _twelve_data_equity_request(canonical, market)
        if request is None:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol="",
                failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
                error="no_twelve_data_provider_request_for_canonical_asset",
                retrieved_at=retrieved_at,
            )
        provider_symbol = f"{request['symbol']}@{request['mic_code']}"
        self.calls += 1
        try:
            quote = self._client.quote(
                request["symbol"],
                mic_code=request["mic_code"],
            ) or {}
        except TwelveDataError as exc:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=_td_failure_class(exc),
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        except Exception as exc:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        if not isinstance(quote, dict):
            quote = {}
        response_symbol = _response_symbol_base(quote.get("symbol") or request["symbol"])
        if response_symbol and response_symbol != canonical:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
                error="twelve_data_symbol_mismatch",
                retrieved_at=retrieved_at,
            )
        mic = str(quote.get("mic_code") or "").strip().upper()
        exchange = str(quote.get("exchange") or mic).strip().upper()
        identity = {mic, exchange}
        if expected == "TRY" and not (identity & TWELVE_DATA_BIST_EXCHANGES):
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
                error="twelve_data_exchange_not_xist",
                retrieved_at=retrieved_at,
            )
        currency_raw = quote.get("currency")
        if not currency_raw:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.CURRENCY_MISMATCH,
                error="twelve_data_currency_ambiguous",
                retrieved_at=retrieved_at,
            )
        result = _validate_equity_quote(
            canonical_symbol=canonical,
            provider=self.name,
            provider_symbol=provider_symbol,
            price_raw=quote.get("close") if quote.get("close") not in (None, "") else quote.get("price"),
            currency_raw=currency_raw,
            exchange_raw=exchange or mic,
            expected_currency=expected,
            as_of=_td_as_of(quote),
            retrieved_at=retrieved_at,
        )
        if result.ok:
            return EquityQuoteResult(
                ok=True,
                canonical_symbol=result.canonical_symbol,
                provider=result.provider,
                provider_symbol=result.provider_symbol,
                price=result.price,
                currency=result.currency,
                as_of=result.as_of,
                retrieved_at=result.retrieved_at,
                exchange=mic or exchange,
            )
        return result

    def get_fx_rate(self, base_currency: str, quote_currency: str) -> FxRateResult:
        base = normalize_currency(base_currency)
        quote = normalize_currency(quote_currency)
        retrieved_at = _now_iso()
        requested = f"{base}/{quote}"
        self.calls += 1
        try:
            payload = self._client.exchange_rate(requested) or {}
        except TwelveDataError as exc:
            return _fx_fail(
                base_currency=base,
                quote_currency=quote,
                provider=self.name,
                failure_class=_td_failure_class(exc),
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        except Exception as exc:
            return _fx_fail(
                base_currency=base,
                quote_currency=quote,
                provider=self.name,
                failure_class=ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        if not isinstance(payload, dict):
            payload = {}
        pair = str(payload.get("symbol") or "").strip().upper().replace("-", "/")
        rate = _numeric_rate(payload.get("rate"))
        as_of = _td_as_of(payload)
        if pair == requested:
            if rate is None:
                return _fx_fail(
                    base_currency=base,
                    quote_currency=quote,
                    provider=self.name,
                    failure_class=ProviderFailureClass.MALFORMED_PRICE,
                    error="twelve_data_fx_rate_invalid",
                    retrieved_at=retrieved_at,
                )
            return FxRateResult(
                ok=True,
                base_currency=base,
                quote_currency=quote,
                rate=rate,
                provider=self.name,
                as_of=as_of,
                retrieved_at=retrieved_at,
                inverted=False,
            )
        inverse = f"{quote}/{base}"
        if pair == inverse:
            if rate is None:
                return _fx_fail(
                    base_currency=base,
                    quote_currency=quote,
                    provider=self.name,
                    failure_class=ProviderFailureClass.MALFORMED_PRICE,
                    error="twelve_data_fx_rate_invalid",
                    retrieved_at=retrieved_at,
                )
            return FxRateResult(
                ok=True,
                base_currency=base,
                quote_currency=quote,
                rate=1.0 / rate,
                provider=self.name,
                as_of=as_of,
                retrieved_at=retrieved_at,
                inverted=True,
            )
        return _fx_fail(
            base_currency=base,
            quote_currency=quote,
            provider=self.name,
            failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
            error="twelve_data_fx_pair_mismatch",
            retrieved_at=retrieved_at,
        )


class BorsaIstanbulEodMarketData:
    """Official Borsa İstanbul THB EOD adapter. Does not persist quotes or FX."""

    name = PROVIDER_BORSA_ISTANBUL_EOD

    def __init__(self, client: Optional[BorsaIstanbulThbClient] = None) -> None:
        self._client = client or BorsaIstanbulThbClient()
        self.calls = 0

    def get_equity_quote(
        self,
        canonical_symbol: str,
        *,
        expected_currency: str,
        market: str,
    ) -> EquityQuoteResult:
        retrieved_at = _now_iso()
        canonical = normalize_symbol(canonical_symbol)
        expected = normalize_currency(expected_currency)
        provider_symbol = borsa_istanbul_eod_series(canonical) or ""
        market_code = str(market or "").strip().upper()
        if market_code not in {"TR", "BIST", "IST", "TURKEY", "XIST"}:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
                error="borsa_istanbul_eod_market_not_bist",
                retrieved_at=retrieved_at,
            )
        if not provider_symbol:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol="",
                failure_class=ProviderFailureClass.INVALID_SYMBOL_MAPPING,
                error="no_borsa_istanbul_eod_series_for_canonical_asset",
                retrieved_at=retrieved_at,
            )
        if expected != "TRY":
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.CURRENCY_MISMATCH,
                error=f"expected_{expected}_got_TRY",
                retrieved_at=retrieved_at,
            )
        self.calls += 1
        try:
            bulletin = self._client.load()
        except BistThbDownloadError as exc:
            failure = (
                ProviderFailureClass.ENDPOINT_UNAVAILABLE
                if exc.status_code in {404, 403, 500}
                else ProviderFailureClass.PROVIDER_ACCESS_FAILURE
            )
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=failure,
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        except Exception as exc:
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.PROVIDER_ACCESS_FAILURE,
                error=str(exc),
                retrieved_at=retrieved_at,
            )
        quote = bulletin.quotes.get(canonical)
        if quote is None:
            if canonical in bulletin.rejected:
                return _equity_fail(
                    canonical_symbol=canonical,
                    provider=self.name,
                    provider_symbol=provider_symbol,
                    failure_class=ProviderFailureClass.MALFORMED_PRICE,
                    error=bulletin.rejected[canonical],
                    retrieved_at=retrieved_at,
                )
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.UNSUPPORTED_SYMBOL,
                error="bist_thb_symbol_missing",
                retrieved_at=retrieved_at,
            )
        if normalize_currency(quote.currency) != "TRY":
            return _equity_fail(
                canonical_symbol=canonical,
                provider=self.name,
                provider_symbol=provider_symbol,
                failure_class=ProviderFailureClass.CURRENCY_MISMATCH,
                error=f"expected_TRY_got_{quote.currency}",
                retrieved_at=retrieved_at,
            )
        return _validate_equity_quote(
            canonical_symbol=canonical,
            provider=self.name,
            provider_symbol=quote.instrument_series,
            price_raw=quote.closing_price,
            currency_raw=quote.currency,
            exchange_raw="XIST",
            expected_currency=expected,
            as_of=quote.trading_date.isoformat(),
            retrieved_at=retrieved_at,
        )

    def get_fx_rate(self, base_currency: str, quote_currency: str) -> FxRateResult:
        return _fx_fail(
            base_currency=normalize_currency(base_currency),
            quote_currency=normalize_currency(quote_currency),
            provider=self.name,
            failure_class=ProviderFailureClass.ENDPOINT_UNAVAILABLE,
            error="borsa_istanbul_eod_does_not_provide_fx",
        )


def _twelve_data_equity_request(canonical: str, market: str) -> Optional[dict]:
    market_code = str(market or "").strip().upper()
    if market_code in {"TR", "BIST", "IST", "TURKEY"}:
        return twelve_data_bist_request(canonical)
    return {"symbol": canonical, "mic_code": ""}


def fetch_equity_quote(
    canonical_symbol: str,
    *,
    expected_currency: str,
    market: str,
    primary: CurrentMarketDataProvider,
    fallback: Optional[CurrentMarketDataProvider] = None,
    fallbacks: Optional[Sequence[CurrentMarketDataProvider]] = None,
    skip_provider_names: Optional[Sequence[str]] = None,
) -> EquityQuoteResult:
    extras = list(fallbacks or [])
    if not extras and fallback is not None:
        extras = [fallback]
    skip = {str(name).strip().upper() for name in (skip_provider_names or ())}

    def _call(provider: CurrentMarketDataProvider) -> EquityQuoteResult:
        return provider.get_equity_quote(
            canonical_symbol,
            expected_currency=expected_currency,
            market=market,
        )

    return _run_provider_chain(_call, primary, extras, skip)


def fetch_fx_rate(
    base_currency: str,
    quote_currency: str,
    *,
    primary: CurrentMarketDataProvider,
    fallback: Optional[CurrentMarketDataProvider] = None,
    fallbacks: Optional[Sequence[CurrentMarketDataProvider]] = None,
    skip_provider_names: Optional[Sequence[str]] = None,
) -> FxRateResult:
    extras = list(fallbacks or [])
    if not extras and fallback is not None:
        extras = [fallback]
    skip = {str(name).strip().upper() for name in (skip_provider_names or ())}

    def _call(provider: CurrentMarketDataProvider) -> FxRateResult:
        return provider.get_fx_rate(base_currency, quote_currency)

    return _run_provider_chain(_call, primary, extras, skip)


def _run_provider_chain(call, primary, extras, skip):
    first = call(primary)
    if first.ok or first.failure_class in INTEGRITY_FAILURES:
        return first
    if first.failure_class not in FALLBACK_ELIGIBLE:
        return first
    last = first
    for provider in extras:
        if str(getattr(provider, "name", "")).strip().upper() in skip:
            continue
        nxt = call(provider)
        last = nxt
        if nxt.ok or nxt.failure_class in INTEGRITY_FAILURES:
            return nxt
        if nxt.failure_class not in FALLBACK_ELIGIBLE:
            return nxt
    return last


def phase_a_activation_allowed(
    equity_results: Sequence[EquityQuoteResult],
    fx_result: Optional[FxRateResult],
) -> bool:
    if fx_result is None or not fx_result.ok or fx_result.rate is None:
        return False
    if normalize_currency(fx_result.base_currency) != "USD":
        return False
    if normalize_currency(fx_result.quote_currency) != "TRY":
        return False
    by_symbol = {row.canonical_symbol: row for row in equity_results}
    for symbol in ("TUPRS", "ASELS", "BIMAS"):
        row = by_symbol.get(symbol)
        if (
            row is None
            or not row.ok
            or row.price is None
            or normalize_currency(row.currency) != "TRY"
        ):
            return False
    return True

