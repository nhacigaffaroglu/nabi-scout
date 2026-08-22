from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping, Optional

from repositories.fx_rate_repository import FxRateRepository
from services.fx_rate_contract import FxConversionResult, FxRateRow
from services.wealth_price_service import normalize_currency


def _parse_rate_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class FxRateService:
    """Read persisted FX rates only — no remote calls on render."""

    STALE_AFTER_DAYS = 7

    def __init__(self, client) -> None:
        self.repo = FxRateRepository(client)
        self.remote_calls = 0

    def get_rate_row(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        on_or_before: Optional[date] = None,
    ) -> Optional[FxRateRow]:
        row = self.repo.get_rate(
            base_currency=base_currency,
            quote_currency=quote_currency,
            on_or_before=on_or_before,
        )
        if not isinstance(row, dict):
            return None
        try:
            rate = float(row.get("rate") or 0.0)
        except (TypeError, ValueError):
            return None
        if rate <= 0:
            return None
        rate_date = _parse_rate_date(str(row.get("rate_date") or ""))
        stale = False
        if rate_date is not None:
            stale = (date.today() - rate_date).days > self.STALE_AFTER_DAYS
        return FxRateRow(
            base_currency=str(row.get("base_currency") or ""),
            quote_currency=str(row.get("quote_currency") or ""),
            rate=rate,
            rate_date=str(row.get("rate_date") or ""),
            source=str(row.get("source") or ""),
            data_quality=str(row.get("data_quality") or "good"),
            stale=stale,
        )

    def convert_amount(
        self,
        *,
        amount: Optional[float],
        from_currency: str,
        to_currency: str,
        on_or_before: Optional[date] = None,
    ) -> FxConversionResult:
        native = normalize_currency(from_currency)
        base = normalize_currency(to_currency)
        if amount is None:
            return FxConversionResult(
                native_amount=None,
                native_currency=native,
                converted_amount=None,
                base_currency=base,
                rate_used=None,
                rate_date=None,
                converted=False,
                unavailable=True,
                stale=False,
                limitation="Tutar yok.",
            )
        if native == base:
            return FxConversionResult(
                native_amount=amount,
                native_currency=native,
                converted_amount=amount,
                base_currency=base,
                rate_used=1.0,
                rate_date=(on_or_before or date.today()).isoformat(),
                converted=True,
                unavailable=False,
                stale=False,
                limitation="",
            )
        direct = self.get_rate_row(
            base_currency=base,
            quote_currency=native,
            on_or_before=on_or_before,
        )
        if direct is not None and direct.rate:
            converted = amount / direct.rate
            return FxConversionResult(
                native_amount=amount,
                native_currency=native,
                converted_amount=converted,
                base_currency=base,
                rate_used=direct.rate,
                rate_date=direct.rate_date,
                converted=True,
                unavailable=False,
                stale=direct.stale,
                limitation="Kur eski olabilir." if direct.stale else "",
            )
        inverse = self.get_rate_row(
            base_currency=native,
            quote_currency=base,
            on_or_before=on_or_before,
        )
        if inverse is not None and inverse.rate:
            converted = amount * inverse.rate
            return FxConversionResult(
                native_amount=amount,
                native_currency=native,
                converted_amount=converted,
                base_currency=base,
                rate_used=inverse.rate,
                rate_date=inverse.rate_date,
                converted=True,
                unavailable=False,
                stale=inverse.stale,
                limitation="Kur eski olabilir." if inverse.stale else "",
            )
        return FxConversionResult(
            native_amount=amount,
            native_currency=native,
            converted_amount=None,
            base_currency=base,
            rate_used=None,
            rate_date=None,
            converted=False,
            unavailable=True,
            stale=False,
            limitation=f"{native}/{base} kuru bulunamadı; dönüşüm yapılmadı.",
        )
