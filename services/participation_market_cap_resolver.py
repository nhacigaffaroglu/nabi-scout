from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from services.participation_financial_contract import ParticipationFinancialInputs
from services.participation_financial_provenance import FinancialFieldProvenance, SOURCE_FMP


@dataclass(frozen=True)
class HistoricalMarketCapEvidence:
    average_market_cap_24m: Optional[float] = None
    average_market_value_equity_36m: Optional[float] = None
    observation_count_24m: int = 0
    observation_count_36m: int = 0
    start_date_24m: Optional[str] = None
    end_date_24m: Optional[str] = None
    start_date_36m: Optional[str] = None
    end_date_36m: Optional[str] = None
    calculation_method: str = "price_times_shares_monthly_mean"
    limitations: Tuple[str, ...] = field(default_factory=tuple)
    source_evidence: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    provider_calls: Dict[str, int] = field(default_factory=dict)


def _parse_date(value: str) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _monthly_last_observations(
    rows: Sequence[Mapping[str, Any]],
    *,
    months: int,
) -> List[float]:
    by_month: Dict[str, tuple[date, float]] = {}
    for row in rows:
        row_date = _parse_date(str(row.get("date") or ""))
        price = row.get("price")
        if row_date is None or price in (None, ""):
            continue
        try:
            price_value = float(price)
        except (TypeError, ValueError):
            continue
        if price_value <= 0:
            continue
        month_key = f"{row_date.year:04d}-{row_date.month:02d}"
        existing = by_month.get(month_key)
        if existing is None or row_date >= existing[0]:
            by_month[month_key] = (row_date, price_value)

    series = sorted(by_month.values(), key=lambda item: item[0], reverse=True)
    return [price for _, price in series[:months]]


def _average(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def resolve_historical_market_cap_evidence(
    *,
    symbol: str,
    fmp_client: Any,
    shares_outstanding: Optional[float] = None,
    profile_market_cap: Optional[float] = None,
) -> HistoricalMarketCapEvidence:
    normalized = str(symbol or "").strip().upper()
    calls: Dict[str, int] = {}
    limitations: list[str] = []
    evidence: list[tuple[str, str]] = [("market_cap_provider", "fmp")]

    if shares_outstanding is None or shares_outstanding <= 0:
        return HistoricalMarketCapEvidence(
            limitations=("Hisse adedi kanıtı olmadan tarihsel piyasa değeri hesaplanmadı.",),
            source_evidence=tuple(evidence),
            provider_calls=calls,
        )

    end = date.today()
    start_36m = end - timedelta(days=36 * 30)
    start_text = start_36m.isoformat()
    end_text = end.isoformat()

    try:
        rows = fmp_client.historical_price_eod_light(
            normalized,
            from_date=start_text,
            to_date=end_text,
        )
        calls["historical_price_eod_light"] = calls.get("historical_price_eod_light", 0) + 1
    except Exception as exc:
        return HistoricalMarketCapEvidence(
            limitations=(f"Tarihsel fiyat verisi alınamadı: {exc.__class__.__name__}",),
            source_evidence=tuple(evidence),
            provider_calls=calls,
        )

    if not rows:
        return HistoricalMarketCapEvidence(
            limitations=("Tarihsel fiyat gözlemi bulunamadı.",),
            source_evidence=tuple(evidence),
            provider_calls=calls,
        )

    monthly_prices_36 = _monthly_last_observations(rows, months=36)
    monthly_prices_24 = monthly_prices_36[:24]
    mcap_36 = [
        price * shares_outstanding
        for price in monthly_prices_36
        if price > 0
    ]
    mcap_24 = [
        price * shares_outstanding
        for price in monthly_prices_24
        if price > 0
    ]

    avg_36 = _average(mcap_36)
    avg_24 = _average(mcap_24)

    if len(mcap_24) < 18:
        limitations.append(
            "24 aylık tarihsel piyasa değeri için yeterli aylık gözlem yok."
        )
        avg_24 = None
    if len(mcap_36) < 24:
        limitations.append(
            "36 aylık piyasa değeri özsermaye penceresi için yeterli aylık gözlem yok."
        )
        avg_36 = None

    if profile_market_cap is not None and avg_24 is None and avg_36 is None:
        limitations.append(
            "Güncel piyasa değeri tarihsel ortalama yerine kullanılmadı."
        )

    evidence.extend(
        (
            ("shares_outstanding", str(shares_outstanding)),
            ("window_36m_start", start_text),
            ("window_36m_end", end_text),
            ("calculation_method", "price_times_shares_monthly_mean"),
        )
    )

    return HistoricalMarketCapEvidence(
        average_market_cap_24m=avg_24,
        average_market_value_equity_36m=avg_36,
        observation_count_24m=len(mcap_24),
        observation_count_36m=len(mcap_36),
        start_date_24m=start_text if mcap_24 else None,
        end_date_24m=end_text if mcap_24 else None,
        start_date_36m=start_text if mcap_36 else None,
        end_date_36m=end_text if mcap_36 else None,
        limitations=tuple(dict.fromkeys(limitations)),
        source_evidence=tuple(evidence),
        provider_calls=calls,
    )


def _merge_source_evidence(
    *evidence_sets: Sequence[tuple[str, str]],
) -> Tuple[Tuple[str, str], ...]:
    merged: dict[str, str] = {}
    for evidence in evidence_sets:
        for key, value in evidence:
            merged[key] = value
    return tuple(merged.items())


def apply_market_cap_evidence_to_inputs(
    inputs: ParticipationFinancialInputs,
    evidence: HistoricalMarketCapEvidence,
) -> ParticipationFinancialInputs:
    merged_evidence = _merge_source_evidence(
        inputs.source_evidence,
        evidence.source_evidence,
    )
    field_provenance = dict(inputs.field_provenance)
    fmp_provenance = FinancialFieldProvenance(
        source=SOURCE_FMP,
        source_fields=("historical_price_eod_light", "shares_outstanding"),
        period=evidence.end_date_36m or evidence.end_date_24m,
    )
    if evidence.average_market_cap_24m is not None:
        field_provenance["average_market_cap_24m"] = fmp_provenance
    if evidence.average_market_value_equity_36m is not None:
        field_provenance["average_market_value_of_equity_36m"] = fmp_provenance
    return replace(
        inputs,
        average_market_cap_24m=evidence.average_market_cap_24m,
        average_market_value_of_equity_36m=evidence.average_market_value_equity_36m,
        source_evidence=merged_evidence,
        field_provenance=tuple(field_provenance.items()),
    )
