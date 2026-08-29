from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from services.fund_intelligence_contract import FundHoldingsSnapshotView
from services.portfolio_allocation_intelligence import TARGET_SUM_EPSILON_PCT
from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.security_master_service import SecurityMasterService
from services.wealth_asset_classification import (
    CASH_SYMBOL,
    resolve_asset_metadata,
)
from services.wealth_contract import (
    ASSET_CLASS_CASH,
    ASSET_CLASS_EQUITY,
    ASSET_CLASS_ETF,
    ASSET_CLASS_FUND,
    ASSET_CLASS_GOLD,
    ASSET_CLASS_SUKUK,
    WealthValidationError,
)
from services.wealth_price_service import normalize_currency

WEIGHT_QUANT = 4
EXPOSURE_DIMENSION_KEY = "ECONOMIC_EXPOSURE"
# Issuer-reported holding weights often round to slightly over 100%.
# Scale aggregated lookthrough buckets only inside this band; raw holding
# weights are never mutated. Larger overflow is still scaled so validation
# cannot crash, but completeness stays incomplete.
ISSUER_WEIGHT_ROUNDING_BAND_PCT = 0.50

# Empty by design: no ticker/name inference. Tests/product may inject mappings.
CANONICAL_STATIC_MAPPINGS: Dict[str, Tuple["EconomicExposure", ...]] = {}

_HOLDING_ASSET_TYPE_MAP = {
    "equity": "equity",
    "stock": "equity",
    "common stock": "equity",
    "sukuk": "sukuk",
    "fixed_income": "fixed_income",
    "fixed income": "fixed_income",
    "bond": "fixed_income",
    "reit": "real_estate",
    "real_estate": "real_estate",
    "real estate": "real_estate",
    "cash": "cash",
    "cash_equivalent": "cash",
    "commodity": "commodity",
    "gold": "commodity",
}


class EconomicExposureBucket(str, Enum):
    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    SUKUK = "sukuk"
    REAL_ESTATE = "real_estate"
    CASH = "cash"
    COMMODITY = "commodity"
    OTHER = "other"
    UNKNOWN = "unknown"


class ExposureEvidenceSource(str, Enum):
    USER_CONFIRMED = "USER_CONFIRMED"
    PERSISTED_FUND_METADATA = "PERSISTED_FUND_METADATA"
    PERSISTED_HOLDINGS_LOOKTHROUGH = "PERSISTED_HOLDINGS_LOOKTHROUGH"
    CANONICAL_STATIC_MAPPING = "CANONICAL_STATIC_MAPPING"
    ASSET_CLASS_FALLBACK = "ASSET_CLASS_FALLBACK"
    UNKNOWN = "UNKNOWN"


class ExposureConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class ExposureCompleteness(str, Enum):
    COMPLETE_EXPOSURE = "COMPLETE_EXPOSURE"
    PARTIAL_EXPOSURE = "PARTIAL_EXPOSURE"
    OBSERVABLE_EXPOSURE = "OBSERVABLE_EXPOSURE"


EXPOSURE_BUCKET_IDS = frozenset(item.value for item in EconomicExposureBucket)
EXPOSURE_BUCKET_ORDER = tuple(item.value for item in EconomicExposureBucket)


@dataclass(frozen=True)
class EconomicExposure:
    exposure_bucket: str
    weight_pct: float
    evidence_source: ExposureEvidenceSource
    confidence: ExposureConfidence
    limitations: Tuple[str, ...] = ()

    def validate(self) -> None:
        bucket = str(self.exposure_bucket or "").strip().lower()
        if bucket not in EXPOSURE_BUCKET_IDS:
            raise WealthValidationError(f"Geçersiz ekonomik maruziyet kovası: {self.exposure_bucket}")
        if float(self.weight_pct) < 0 or float(self.weight_pct) > 100:
            raise WealthValidationError("Maruziyet ağırlığı 0–100 aralığında olmalı.")


@dataclass(frozen=True)
class InstrumentExposureView:
    symbol: str
    instrument_class: str
    economic_exposures: Tuple[EconomicExposure, ...]
    evidence_complete: bool
    valuation_available: bool
    observable_market_value: Optional[float]
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "instrument_class": self.instrument_class,
            "economic_exposures": [
                {
                    "exposure_bucket": row.exposure_bucket,
                    "weight_pct": row.weight_pct,
                    "evidence_source": row.evidence_source.value,
                    "confidence": row.confidence.value,
                    "limitations": list(row.limitations),
                }
                for row in self.economic_exposures
            ],
            "evidence_complete": self.evidence_complete,
            "valuation_available": self.valuation_available,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class PortfolioExposureBucket:
    bucket_id: str
    observable_market_value: Optional[float]
    observable_weight_pct: Optional[float]
    contributing_symbols: Tuple[str, ...]
    unpriced_symbols: Tuple[str, ...]
    evidence_coverage_pct: float
    confidence: ExposureConfidence
    limitations: Tuple[str, ...]


@dataclass(frozen=True)
class PortfolioEconomicExposureView:
    completeness: ExposureCompleteness
    valuation_coverage_pct: float
    exposure_classification_coverage_pct: float
    observable_total_market_value: float
    instruments: Tuple[InstrumentExposureView, ...]
    buckets: Tuple[PortfolioExposureBucket, ...]
    limitations: Tuple[str, ...]
    generated_from: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "completeness": self.completeness.value,
            "valuation_coverage_pct": self.valuation_coverage_pct,
            "exposure_classification_coverage_pct": self.exposure_classification_coverage_pct,
            "observable_total_market_value": self.observable_total_market_value,
            "instruments": [row.to_dict() for row in self.instruments],
            "buckets": [
                {
                    "bucket_id": row.bucket_id,
                    "observable_weight_pct": row.observable_weight_pct,
                    "contributing_symbols": list(row.contributing_symbols),
                    "unpriced_symbols": list(row.unpriced_symbols),
                    "confidence": row.confidence.value,
                    "limitations": list(row.limitations),
                }
                for row in self.buckets
            ],
            "limitations": list(self.limitations),
        }


def validate_exposure_weights(
    exposures: Sequence[EconomicExposure],
    *,
    complete: bool,
) -> None:
    if not exposures:
        raise WealthValidationError("Maruziyet kaydı gerekli.")
    seen: set[str] = set()
    total = 0.0
    for row in exposures:
        row.validate()
        key = str(row.exposure_bucket).strip().lower()
        if key in seen:
            raise WealthValidationError("Aynı kova tekrarlanamaz.")
        seen.add(key)
        total += float(row.weight_pct)
    if complete and abs(total - 100.0) > TARGET_SUM_EPSILON_PCT:
        raise WealthValidationError(
            f"Maruziyet ağırlıkları ~100% toplamalı; mevcut {total:.4f}."
        )
    if not complete and total - 100.0 > TARGET_SUM_EPSILON_PCT:
        raise WealthValidationError("Eksik maruziyet 100%'ü aşamaz.")


def _round(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), WEIGHT_QUANT)


def _all_rows(view: PortfolioIntelligenceView) -> Tuple[PositionValuationRow, ...]:
    return tuple(
        [
            *view.priced_positions,
            *view.unpriced_positions,
            *view.foreign_currency_positions,
        ]
    )


def _unvalued_row(position: Mapping[str, Any], asset: Mapping[str, Any]) -> PositionValuationRow:
    symbol = str(asset.get("symbol") or "").strip().upper()
    currency = normalize_currency(asset.get("currency"))
    quantity = float(position.get("quantity") or 0.0)
    average_cost = float(position.get("average_cost") or 0.0)
    return PositionValuationRow(
        position_id=str(position.get("id") or f"unvalued-{symbol}"),
        account_id=str(position.get("account_id") or ""),
        asset_id=str(position.get("asset_id") or ""),
        symbol=symbol,
        asset_class=str(asset.get("asset_class") or ""),
        account_name="",
        quantity=quantity,
        average_cost=average_cost,
        valuation_currency=currency,
        price=None,
        price_available=False,
        market_value=None,
        cost_basis=quantity * average_cost,
        unrealized_pl=None,
        weight_pct=None,
        is_cash=False,
        included_in_base_totals=False,
    )


def _recover_rows(
    *,
    existing: Sequence[PositionValuationRow],
    positions: Optional[Sequence[dict]],
    assets: Optional[Sequence[dict]],
) -> Tuple[PositionValuationRow, ...]:
    asset_by_id = {str(row.get("id") or ""): row for row in (assets or [])}
    seen = {str(row.symbol or "").strip().upper() for row in existing if str(row.symbol or "").strip()}
    recovered: list[PositionValuationRow] = []
    for position in positions or []:
        if float(position.get("quantity") or 0) <= 0:
            continue
        asset = asset_by_id.get(str(position.get("asset_id") or ""), {})
        symbol = str(asset.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        recovered.append(_unvalued_row(position, asset))
    return tuple(recovered)


def _instrument_class(row: PositionValuationRow) -> str:
    if row.is_cash or str(row.symbol or "").strip().upper() == CASH_SYMBOL:
        return ASSET_CLASS_CASH
    asset_class, _market, kind, _status = resolve_asset_metadata(
        row.symbol, currency=row.valuation_currency
    )
    if kind == "etf" or asset_class in {ASSET_CLASS_ETF, ASSET_CLASS_FUND}:
        return ASSET_CLASS_ETF
    raw = str(row.asset_class or "").strip().lower()
    if raw in {
        ASSET_CLASS_EQUITY,
        ASSET_CLASS_CASH,
        ASSET_CLASS_SUKUK,
        ASSET_CLASS_GOLD,
        ASSET_CLASS_ETF,
        ASSET_CLASS_FUND,
        "fixed_income",
    }:
        return raw
    if asset_class:
        return str(asset_class).strip().lower()
    return raw or "other"


def _fallback_bucket(instrument_class: str) -> Optional[str]:
    if instrument_class == ASSET_CLASS_EQUITY:
        return EconomicExposureBucket.EQUITY.value
    if instrument_class == ASSET_CLASS_CASH:
        return EconomicExposureBucket.CASH.value
    if instrument_class == ASSET_CLASS_SUKUK:
        return EconomicExposureBucket.SUKUK.value
    if instrument_class == ASSET_CLASS_GOLD:
        return EconomicExposureBucket.COMMODITY.value
    if instrument_class == "fixed_income":
        return EconomicExposureBucket.FIXED_INCOME.value
    return None


def _unknown(*, limitation: str) -> Tuple[EconomicExposure, ...]:
    return (
        EconomicExposure(
            exposure_bucket=EconomicExposureBucket.UNKNOWN.value,
            weight_pct=100.0,
            evidence_source=ExposureEvidenceSource.UNKNOWN,
            confidence=ExposureConfidence.UNKNOWN,
            limitations=(limitation,),
        ),
    )


def _clone_with_source(
    rows: Sequence[EconomicExposure],
    *,
    source: ExposureEvidenceSource,
    confidence: ExposureConfidence,
) -> Tuple[EconomicExposure, ...]:
    return tuple(
        EconomicExposure(
            exposure_bucket=row.exposure_bucket,
            weight_pct=float(row.weight_pct),
            evidence_source=source,
            confidence=confidence,
            limitations=row.limitations,
        )
        for row in rows
    )


def _from_mapping(raw: Sequence[EconomicExposure]) -> Tuple[EconomicExposure, ...]:
    rows = tuple(raw)
    validate_exposure_weights(rows, complete=True)
    return rows


def _scale_issuer_reported_weights(
    weights: Dict[str, float],
) -> Tuple[Dict[str, float], str]:
    total = sum(weights.values())
    if total <= 100.0 + TARGET_SUM_EPSILON_PCT:
        return weights, ""
    scale = 100.0 / total
    scaled = {bucket: weight * scale for bucket, weight in weights.items()}
    if total <= 100.0 + ISSUER_WEIGHT_ROUNDING_BAND_PCT:
        return scaled, "ISSUER_WEIGHT_ROUNDING_NORMALIZED"
    return scaled, "MATERIAL_ISSUER_WEIGHT_OVERFLOW"


def _holding_policy_bucket(
    holding,
    *,
    security_master: SecurityMasterService,
) -> str:
    asset_type = str(holding.asset_type or "").strip().lower()
    bucket = _HOLDING_ASSET_TYPE_MAP.get(asset_type)
    if bucket is not None:
        return bucket
    resolution = security_master.resolve_security(holding.underlying_symbol)
    policy = resolution.policy_asset_type
    if policy:
        mapped = _HOLDING_ASSET_TYPE_MAP.get(policy)
        if mapped is not None:
            return mapped
    return EconomicExposureBucket.UNKNOWN.value


def _lookthrough_exposures(
    snapshot: FundHoldingsSnapshotView,
    *,
    security_master: Optional[SecurityMasterService] = None,
) -> Tuple[Tuple[EconomicExposure, ...], bool]:
    master = security_master or SecurityMasterService()
    weights: Dict[str, float] = {}
    mapped = 0.0
    for holding in snapshot.holdings:
        slice_pct = float(holding.weight_pct or 0.0)
        if slice_pct <= 0:
            continue
        bucket = _holding_policy_bucket(holding, security_master=master)
        weights[bucket] = weights.get(bucket, 0.0) + slice_pct
        if bucket != EconomicExposureBucket.UNKNOWN.value:
            mapped += slice_pct
    weights, scale_limitation = _scale_issuer_reported_weights(weights)
    coverage = float(snapshot.coverage_pct) if snapshot.coverage_pct is not None else mapped
    remainder = max(0.0, 100.0 - sum(weights.values()))
    if remainder > TARGET_SUM_EPSILON_PCT:
        weights[EconomicExposureBucket.UNKNOWN.value] = (
            weights.get(EconomicExposureBucket.UNKNOWN.value, 0.0) + remainder
        )
    if not weights:
        return _unknown(limitation="LOOKTHROUGH_EMPTY"), False
    complete = (
        abs(sum(weights.values()) - 100.0) <= TARGET_SUM_EPSILON_PCT
        and EconomicExposureBucket.UNKNOWN.value not in weights
        and (snapshot.coverage_pct is None or abs(float(snapshot.coverage_pct) - 100.0) <= 0.5)
        and scale_limitation != "MATERIAL_ISSUER_WEIGHT_OVERFLOW"
    )
    confidence = ExposureConfidence.HIGH if complete else ExposureConfidence.MEDIUM
    rows = tuple(
        EconomicExposure(
            exposure_bucket=bucket,
            weight_pct=_round(weight) or 0.0,
            evidence_source=ExposureEvidenceSource.PERSISTED_HOLDINGS_LOOKTHROUGH,
            confidence=confidence,
            limitations=tuple(
                item
                for item in (
                    "LOOKTHROUGH_UNMAPPED" if bucket == EconomicExposureBucket.UNKNOWN.value else "",
                    scale_limitation,
                )
                if item
            ),
        )
        for bucket, weight in sorted(weights.items(), key=lambda item: EXPOSURE_BUCKET_ORDER.index(item[0]))
    )
    validate_exposure_weights(rows, complete=complete)
    return rows, complete


def classify_instrument_exposure(
    row: PositionValuationRow,
    *,
    user_overrides: Optional[Mapping[str, Sequence[EconomicExposure]]] = None,
    canonical_mappings: Optional[Mapping[str, Sequence[EconomicExposure]]] = None,
    fund_snapshots: Optional[Mapping[str, FundHoldingsSnapshotView]] = None,
    security_master: Optional[SecurityMasterService] = None,
) -> InstrumentExposureView:
    symbol = str(row.symbol or "").strip().upper()
    instrument_class = _instrument_class(row)
    valuation_available = bool(row.price_available and row.market_value is not None)
    limitations: list[str] = []
    if not valuation_available:
        limitations.append("VALUATION_UNAVAILABLE")
    overrides = user_overrides or {}
    canonical = canonical_mappings if canonical_mappings is not None else CANONICAL_STATIC_MAPPINGS
    snapshots = fund_snapshots or {}

    if symbol in overrides:
        exposures = _clone_with_source(
            _from_mapping(overrides[symbol]),
            source=ExposureEvidenceSource.USER_CONFIRMED,
            confidence=ExposureConfidence.HIGH,
        )
        complete = True
    elif symbol in canonical:
        exposures = _clone_with_source(
            _from_mapping(canonical[symbol]),
            source=ExposureEvidenceSource.CANONICAL_STATIC_MAPPING,
            confidence=ExposureConfidence.HIGH,
        )
        complete = True
    elif instrument_class in {ASSET_CLASS_ETF, ASSET_CLASS_FUND} and symbol in snapshots:
        snapshot = snapshots[symbol]
        if snapshot.holdings:
            exposures, complete = _lookthrough_exposures(
                snapshot,
                security_master=security_master,
            )
        else:
            exposures = _unknown(limitation="HOLDINGS_LOOKTHROUGH_EMPTY")
            complete = False
            limitations.append("EXPOSURE_UNKNOWN")
    elif instrument_class in {ASSET_CLASS_ETF, ASSET_CLASS_FUND}:
        exposures = _unknown(limitation="ETF_EXPOSURE_EVIDENCE_MISSING")
        complete = False
        limitations.append("EXPOSURE_UNKNOWN")
    else:
        bucket = _fallback_bucket(instrument_class)
        if bucket is None:
            exposures = _unknown(limitation="ASSET_CLASS_EXPOSURE_UNKNOWN")
            complete = False
            limitations.append("EXPOSURE_UNKNOWN")
        else:
            exposures = (
                EconomicExposure(
                    exposure_bucket=bucket,
                    weight_pct=100.0,
                    evidence_source=ExposureEvidenceSource.ASSET_CLASS_FALLBACK,
                    confidence=ExposureConfidence.HIGH,
                    limitations=(),
                ),
            )
            complete = True
    if not complete:
        limitations.append("EXPOSURE_CLASSIFICATION_INCOMPLETE")
    return InstrumentExposureView(
        symbol=symbol,
        instrument_class=instrument_class,
        economic_exposures=exposures,
        evidence_complete=complete,
        valuation_available=valuation_available,
        observable_market_value=_round(float(row.market_value) if valuation_available else None),
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _confidence_summary(values: Sequence[ExposureConfidence]) -> ExposureConfidence:
    if not values:
        return ExposureConfidence.UNKNOWN
    order = {
        ExposureConfidence.UNKNOWN: 0,
        ExposureConfidence.LOW: 1,
        ExposureConfidence.MEDIUM: 2,
        ExposureConfidence.HIGH: 3,
    }
    return min(values, key=lambda item: order[item])


def build_economic_exposure(
    portfolio_view: PortfolioIntelligenceView,
    *,
    fund_snapshots: Optional[Mapping[str, FundHoldingsSnapshotView]] = None,
    user_overrides: Optional[Mapping[str, Sequence[EconomicExposure]]] = None,
    canonical_mappings: Optional[Mapping[str, Sequence[EconomicExposure]]] = None,
    assets: Optional[Sequence[dict]] = None,
    positions: Optional[Sequence[dict]] = None,
    security_master: Optional[SecurityMasterService] = None,
) -> PortfolioEconomicExposureView:
    """Observable economic exposure. No providers, no writes, no ticker-name inference."""
    existing = _all_rows(portfolio_view)
    recovered = _recover_rows(existing=existing, positions=positions, assets=assets)
    rows = tuple(
        sorted(
            (*existing, *recovered),
            key=lambda item: (
                str(item.symbol or "").upper(),
                str(item.position_id or ""),
                str(item.account_id or ""),
            ),
        )
    )
    classified_by_symbol: Dict[str, InstrumentExposureView] = {}
    instruments_list: list[InstrumentExposureView] = []
    for row in rows:
        symbol = str(row.symbol or "").strip().upper()
        if not symbol:
            continue
        cached = classified_by_symbol.get(symbol)
        if cached is None:
            cached = classify_instrument_exposure(
                row,
                user_overrides=user_overrides,
                canonical_mappings=canonical_mappings,
                fund_snapshots=fund_snapshots,
                security_master=security_master,
            )
            classified_by_symbol[symbol] = cached
        row_priced = bool(row.price_available and row.market_value is not None)
        row_mv = _round(float(row.market_value)) if row_priced else None
        instruments_list.append(
            replace(
                cached,
                observable_market_value=row_mv,
                valuation_available=row_priced,
            )
        )
    instruments = tuple(instruments_list)
    priced_mv = float(portfolio_view.priced_total_market_value or 0.0)
    classified_mv = 0.0
    bucket_mv: Dict[str, float] = {key: 0.0 for key in EXPOSURE_BUCKET_ORDER}
    bucket_symbols: Dict[str, list[str]] = {key: [] for key in EXPOSURE_BUCKET_ORDER}
    bucket_unpriced: Dict[str, list[str]] = {key: [] for key in EXPOSURE_BUCKET_ORDER}
    bucket_conf: Dict[str, list[ExposureConfidence]] = {key: [] for key in EXPOSURE_BUCKET_ORDER}
    for instrument in instruments:
        mv = instrument.observable_market_value
        classified = instrument.evidence_complete and not any(
            row.exposure_bucket == EconomicExposureBucket.UNKNOWN.value
            for row in instrument.economic_exposures
        )
        if mv is not None and classified:
            classified_mv += mv
        for slice_row in instrument.economic_exposures:
            bucket = slice_row.exposure_bucket
            if mv is not None:
                bucket_mv[bucket] += mv * (float(slice_row.weight_pct) / 100.0)
                bucket_symbols[bucket].append(instrument.symbol)
            else:
                bucket_unpriced[bucket].append(instrument.symbol)
            bucket_conf[bucket].append(slice_row.confidence)

    buckets = []
    for bucket_id in EXPOSURE_BUCKET_ORDER:
        mv = bucket_mv[bucket_id]
        unpriced = tuple(sorted(set(bucket_unpriced[bucket_id])))
        contributors = tuple(sorted(set(bucket_symbols[bucket_id])))
        weight = None if priced_mv <= 0 else _round((mv / priced_mv) * 100.0)
        if unpriced and not contributors:
            weight = None
        limitations = []
        if unpriced:
            limitations.append("UNPRICED_HOLDINGS_NOT_ZERO")
        if bucket_id == EconomicExposureBucket.UNKNOWN.value and (contributors or unpriced):
            limitations.append("UNKNOWN_EXPOSURE_PRESERVED")
        coverage = 100.0 if contributors and not unpriced else (0.0 if unpriced and not contributors else 50.0)
        if contributors and unpriced:
            coverage = 50.0
        elif contributors:
            coverage = 100.0
        elif unpriced:
            coverage = 0.0
        else:
            coverage = 100.0
        buckets.append(
            PortfolioExposureBucket(
                bucket_id=bucket_id,
                observable_market_value=_round(mv if contributors else None),
                observable_weight_pct=None if not contributors else weight,
                contributing_symbols=contributors,
                unpriced_symbols=unpriced,
                evidence_coverage_pct=coverage,
                confidence=_confidence_summary(bucket_conf[bucket_id]),
                limitations=tuple(limitations),
            )
        )

    total_positions = max(int(portfolio_view.total_position_count or len(rows)), 1)
    priced_count = int(portfolio_view.priced_position_count or 0)
    valuation_coverage = _round((priced_count / total_positions) * 100.0) or 0.0
    classification_coverage = _round((classified_mv / priced_mv) * 100.0) if priced_mv > 0 else 0.0
    valuation_complete = priced_count == int(portfolio_view.total_position_count or priced_count) and not any(
        not row.valuation_available for row in instruments
    )
    unknown_priced = any(
        row.valuation_available
        and any(item.exposure_bucket == EconomicExposureBucket.UNKNOWN.value for item in row.economic_exposures)
        for row in instruments
    )
    if valuation_complete and not unknown_priced and classification_coverage >= 100.0 - TARGET_SUM_EPSILON_PCT:
        completeness = ExposureCompleteness.COMPLETE_EXPOSURE
    elif unknown_priced or not valuation_complete:
        completeness = ExposureCompleteness.PARTIAL_EXPOSURE
    else:
        completeness = ExposureCompleteness.OBSERVABLE_EXPOSURE

    limitations = []
    if not valuation_complete:
        limitations.append("VALUATION_INCOMPLETE")
    if unknown_priced or classification_coverage < 100.0 - TARGET_SUM_EPSILON_PCT:
        limitations.append("EXPOSURE_CLASSIFICATION_INCOMPLETE")
    limitations.append("OBSERVABLE_EXPOSURE_ONLY")
    return PortfolioEconomicExposureView(
        completeness=completeness,
        valuation_coverage_pct=float(valuation_coverage),
        exposure_classification_coverage_pct=float(classification_coverage or 0.0),
        observable_total_market_value=_round(priced_mv) or 0.0,
        instruments=instruments,
        buckets=tuple(buckets),
        limitations=tuple(dict.fromkeys(limitations)),
        generated_from=(
            "portfolio_intelligence_view",
            "resolve_asset_metadata",
            "persisted_fund_holdings_optional",
            "security_master_optional",
        ),
    )
