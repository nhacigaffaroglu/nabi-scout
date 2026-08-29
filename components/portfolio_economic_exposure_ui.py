from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from components.nabi_design_system import render_section_title, render_status_badge
from components.portfolio_allocation_center_ui import (
    CONTRIB_AMOUNT_KEY,
    CONTRIB_CURRENCY_KEY,
    FX_REQUIRED_COPY,
    HEADING,
    PERSISTED_STATUS,
    PLANNED_CONTRIBUTION_LABEL,
    RESET_FAILED,
    RESET_LABEL,
    SAVE_FAILED,
    SAVE_LABEL,
    SIMULATION_NOTE,
    UNCONFIGURED_ROUTING,
    _session_conversion,
    contribution_defaults,
)
from services.portfolio_allocation_policy_service import AllocationPolicyStoreError
from services.fund_intelligence_contract import FundHoldingsSnapshotView
from services.portfolio_allocation_intelligence import (
    TARGET_SUM_EPSILON_PCT,
    AllocationBucket,
    AllocationCompleteness,
    AllocationDimension,
    AllocationIntelligenceView,
    AllocationPolicy,
    AllocationPolicyStatus,
    AllocationProvenance,
    AllocationTarget,
    DriftResult,
    DriftStatus,
    RoutingEvidenceQuality,
    RoutingStatus,
    build_allocation_intelligence,
    policy_is_configured,
)
from services.portfolio_economic_exposure import (
    EXPOSURE_BUCKET_ORDER,
    EconomicExposure,
    EconomicExposureBucket,
    ExposureConfidence,
    ExposureEvidenceSource,
    InstrumentExposureView,
    PortfolioEconomicExposureView,
    build_economic_exposure,
)
from services.portfolio_intelligence_contract import (
    PortfolioIntelligenceView,
    PositionValuationRow,
)
from services.wealth_contract import ASSET_CLASS_ETF, ASSET_CLASS_FUND, WealthValidationError

VIEW_ASSET_CLASS = "ASSET_CLASS"
VIEW_ECONOMIC_EXPOSURE = "ECONOMIC_EXPOSURE"
DIMENSION_VIEW_KEY = "portfolio_allocation_dimension_view"
DIMENSION_LABELS = {
    VIEW_ASSET_CLASS: "Varlık Türü",
    VIEW_ECONOMIC_EXPOSURE: "Ekonomik Maruziyet",
}
OVERRIDE_KEY = "portfolio_economic_exposure_user_overrides"
APPLIED_WEIGHTS_KEY = "portfolio_economic_exposure_applied_weights"
DRAFT_WEIGHT_KEY_PREFIX = "portfolio_economic_exposure_draft_"
PERSISTED_FLAG_KEY = "portfolio_economic_exposure_persisted"
SAVE_ERROR_KEY = "portfolio_economic_exposure_save_error"
RESET_ERROR_KEY = "portfolio_economic_exposure_reset_error"
UNKNOWN_ETF_HEADING = "Sınıflandırılamayan ETF’ler"
USER_CONFIRMED_LABEL = "Kullanıcı sınıflandırması"
VALUATION_COVERAGE_LABEL = "Değerleme kapsamı"
CLASSIFICATION_COVERAGE_LABEL = "Ekonomik maruziyet sınıflandırma kapsamı"
GROWTH_TARGET_LABEL = "Büyüme hedef dağılımı — planlama tercihi"
SESSION_TARGET_NOTE = (
    "Ekonomik maruziyet hedefi kaydedilmeden sapma hesaplanmaz. "
    "Otomatik kayıt yok."
)
INCOMPLETE_DRIFT_NOTE = (
    "Ekonomik maruziyet sınıflandırması eksik olduğu için bazı sapma sonuçları belirsiz olabilir."
)
INDETERMINATE_EXPOSURE_ROUTING = (
    "Ekonomik maruziyet sınıflandırması eksik olduğu için katkı yönlendirmesi belirsiz."
)
GROWTH_ECONOMIC_EXPOSURE_WEIGHTS = {
    "equity": 75.0,
    "sukuk": 10.0,
    "fixed_income": 5.0,
    "real_estate": 5.0,
    "cash": 5.0,
    "commodity": 0.0,
    "other": 0.0,
}
UNKNOWN_EVIDENCE = "unavailable / no persisted look-through"
CONFIRMABLE_BUCKETS = (
    "equity",
    "fixed_income",
    "sukuk",
    "real_estate",
    "cash",
    "commodity",
    "other",
)
EXPOSURE_TARGET_BUCKETS = CONFIRMABLE_BUCKETS
EXPOSURE_BUCKET_LABELS = {
    "equity": "Hisse",
    "fixed_income": "Sabit Getirili",
    "sukuk": "Sukuk",
    "real_estate": "Gayrimenkul",
    "cash": "Nakit",
    "commodity": "Emtia",
    "other": "Diğer",
    "unknown": "Bilinmiyor",
}
INSTRUMENT_CLASS_LABELS = {
    "equity": "Hisse",
    "etf": "ETF",
    "fund": "Fon",
    "sukuk": "Sukuk",
    "cash": "Nakit",
    "gold": "Altın",
    "fixed_income": "Sabit Getirili",
}
EVIDENCE_LABELS = {
    ExposureEvidenceSource.USER_CONFIRMED: USER_CONFIRMED_LABEL,
    ExposureEvidenceSource.PERSISTED_HOLDINGS_LOOKTHROUGH: "persisted look-through",
    ExposureEvidenceSource.PERSISTED_FUND_METADATA: "persisted fund metadata",
    ExposureEvidenceSource.CANONICAL_STATIC_MAPPING: "canonical mapping",
    ExposureEvidenceSource.ASSET_CLASS_FALLBACK: "asset-class fallback",
    ExposureEvidenceSource.UNKNOWN: UNKNOWN_EVIDENCE,
}
STATUS_LABELS = {
    DriftStatus.OVERWEIGHT: "Hedef Üstü",
    DriftStatus.UNDERWEIGHT: "Hedef Altı",
    DriftStatus.ON_TARGET: "Hedefte",
    DriftStatus.INDETERMINATE: "Belirsiz",
}
STATUS_TONES = {
    DriftStatus.OVERWEIGHT: "warning",
    DriftStatus.UNDERWEIGHT: "warning",
    DriftStatus.ON_TARGET: "success",
    DriftStatus.INDETERMINATE: "info",
}
EVIDENCE_QUALITY_LABELS = {
    RoutingEvidenceQuality.COMPLETE: "tamam",
    RoutingEvidenceQuality.PARTIAL: "kısmi",
    RoutingEvidenceQuality.UNAVAILABLE: "yok",
}


@dataclass(frozen=True)
class PresentedUnknownEtf:
    symbol: str
    instrument_class: str
    economic_exposure: str
    evidence: str


@dataclass(frozen=True)
class PresentedExposureSlice:
    bucket_id: str
    label: str
    weight_pct: float


@dataclass(frozen=True)
class PresentedInstrumentRow:
    symbol: str
    instrument_class: str
    slices: Tuple[PresentedExposureSlice, ...]
    slice_text: str
    evidence: str
    user_confirmed: bool
    valuation_available: bool
    unknown: bool


@dataclass(frozen=True)
class PresentedExposureBucket:
    bucket_id: str
    label: str
    observable_weight_pct: Optional[float]
    target_weight_pct: Optional[float]
    drift_pct: Optional[float]
    status_label: Optional[str]
    status_tone: str
    indeterminate: bool
    unpriced_symbols: Tuple[str, ...]
    contributing_symbols: Tuple[str, ...]
    limitation: Optional[str]


@dataclass(frozen=True)
class PresentedExposureRouting:
    message: str
    status: str
    best_bucket_label: Optional[str]
    before_drift: Optional[float]
    after_drift: Optional[float]
    improvement: Optional[float]
    evidence_quality: Optional[str]
    limitation: Optional[str]


@dataclass(frozen=True)
class EconomicExposurePresentation:
    heading: str
    view_asset_class_label: str
    view_economic_label: str
    valuation_coverage_label: str
    valuation_coverage_pct: float
    classification_coverage_label: str
    classification_coverage_pct: float
    unknown_etf_heading: str
    user_confirmed_label: str
    session_target_note: str
    remaining_pct: float
    draft_total: float
    can_apply: bool
    apply_error: Optional[str]
    configured: bool
    buckets: Tuple[PresentedExposureBucket, ...]
    instruments: Tuple[PresentedInstrumentRow, ...]
    unknown_etfs: Tuple[PresentedUnknownEtf, ...]
    routing: PresentedExposureRouting
    persisted: bool = False
    growth_label: Optional[str] = None
    incomplete_note: Optional[str] = None
    persistence_message: Optional[str] = None


def draft_weight_key(bucket_id: str) -> str:
    return f"{DRAFT_WEIGHT_KEY_PREFIX}{bucket_id}"


def _as_float(value: Any) -> float:
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def format_weight_pct(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return f"{text}%"


def draft_weights_from_session(session_state: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    source = session_state or {}
    return {
        bucket: max(_as_float(source.get(draft_weight_key(bucket), 0.0)), 0.0)
        for bucket in EXPOSURE_TARGET_BUCKETS
    }


def remaining_target_pct(weights: Mapping[str, float]) -> float:
    return round(
        100.0 - sum(float(weights.get(bucket, 0.0)) for bucket in EXPOSURE_TARGET_BUCKETS),
        4,
    )


def validate_exposure_target_weights(weights: Mapping[str, float]) -> Optional[str]:
    total = 0.0
    for bucket in EXPOSURE_TARGET_BUCKETS:
        value = float(weights.get(bucket, 0.0))
        if value < 0:
            return "Hedef ağırlık negatif olamaz."
        if value > 100:
            return "Hedef ağırlık 100'ü aşamaz."
        total += value
    if "unknown" in {str(key).strip().lower() for key in weights}:
        unknown_weight = float(weights.get("unknown") or 0.0)
        if unknown_weight:
            return "Bilinmiyor hedef kova olamaz."
    if abs(total - 100.0) > TARGET_SUM_EPSILON_PCT:
        return f"Toplam {total:.1f}% — hedef 100% olmalı, otomatik dengeleme yok."
    return None


def policy_from_exposure_weights(weights: Mapping[str, float]) -> Optional[AllocationPolicy]:
    normalized = {str(key).lower(): _as_float(value) for key, value in weights.items()}
    if validate_exposure_target_weights(normalized):
        return None
    if normalized.get("unknown"):
        return None
    targets = tuple(
        AllocationTarget(
            bucket_id=bucket,
            dimension=AllocationDimension.ECONOMIC_EXPOSURE,
            target_weight_pct=float(normalized.get(bucket, 0.0)),
            source=AllocationProvenance.USER_DEFINED,
        )
        for bucket in EXPOSURE_TARGET_BUCKETS
    )
    policy = AllocationPolicy(targets=targets, provenance=AllocationProvenance.USER_DEFINED)
    policy.validate()
    return policy


def growth_economic_exposure_policy() -> AllocationPolicy:
    policy = policy_from_exposure_weights(GROWTH_ECONOMIC_EXPOSURE_WEIGHTS)
    if policy is None:
        raise WealthValidationError("Büyüme hedef dağılımı geçersiz.")
    return policy


def is_growth_economic_exposure_weights(weights: Mapping[str, float]) -> bool:
    for bucket, expected in GROWTH_ECONOMIC_EXPOSURE_WEIGHTS.items():
        if abs(float(weights.get(bucket, 0.0)) - float(expected)) > TARGET_SUM_EPSILON_PCT:
            return False
    return True


def weights_from_exposure_policy(policy: AllocationPolicy) -> Dict[str, float]:
    by_id = {
        str(target.bucket_id).strip().lower(): float(target.target_weight_pct)
        for target in policy.targets
        if target.dimension == AllocationDimension.ECONOMIC_EXPOSURE
    }
    return {bucket: float(by_id.get(bucket, 0.0)) for bucket in EXPOSURE_TARGET_BUCKETS}


def hydrate_economic_exposure_from_policy(session_state: Any, policy: AllocationPolicy) -> None:
    weights = weights_from_exposure_policy(policy)
    session_state[APPLIED_WEIGHTS_KEY] = dict(weights)
    for bucket, value in weights.items():
        session_state[draft_weight_key(bucket)] = float(value)
    session_state[PERSISTED_FLAG_KEY] = True


def save_economic_exposure_policy_from_session(
    session_state: Any,
    *,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> Optional[str]:
    weights = draft_weights_from_session(session_state)
    error = validate_exposure_target_weights(weights)
    if error:
        return error
    policy = policy_from_exposure_weights(weights)
    if policy is None:
        return "Hedef dağılım henüz tanımlanmadı."
    if policy_service is not None and portfolio_id:
        try:
            stored = policy_service.save_policy(portfolio_id, policy)
        except AllocationPolicyStoreError as exc:
            return str(exc) or SAVE_FAILED
        except Exception:
            return SAVE_FAILED
        weights = weights_from_exposure_policy(stored)
        session_state[PERSISTED_FLAG_KEY] = True
    else:
        session_state[PERSISTED_FLAG_KEY] = False
    session_state[APPLIED_WEIGHTS_KEY] = dict(weights)
    for bucket, value in weights.items():
        session_state[draft_weight_key(bucket)] = float(value)
    session_state.pop(SAVE_ERROR_KEY, None)
    session_state.pop(RESET_ERROR_KEY, None)
    return None


def reset_economic_exposure_policy_session(
    session_state: Any,
    *,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> Optional[str]:
    if policy_service is not None and portfolio_id:
        try:
            policy_service.delete_policy(portfolio_id)
        except AllocationPolicyStoreError as exc:
            return str(exc) or RESET_FAILED
        except Exception:
            return RESET_FAILED
    session_state.pop(APPLIED_WEIGHTS_KEY, None)
    for bucket in EXPOSURE_TARGET_BUCKETS:
        session_state[draft_weight_key(bucket)] = 0.0
    session_state[PERSISTED_FLAG_KEY] = False
    session_state.pop(SAVE_ERROR_KEY, None)
    session_state.pop(RESET_ERROR_KEY, None)
    return None


def policy_from_exposure_session(session_state: Optional[Mapping[str, Any]]) -> Optional[AllocationPolicy]:
    source = session_state or {}
    applied = source.get(APPLIED_WEIGHTS_KEY)
    if not isinstance(applied, dict) or not applied:
        return None
    return policy_from_exposure_weights(applied)


def apply_exposure_targets_to_session(session_state: Any) -> Optional[str]:
    weights = draft_weights_from_session(session_state)
    error = validate_exposure_target_weights(weights)
    if error:
        return error
    policy = policy_from_exposure_weights(weights)
    if policy is None:
        return "Hedef dağılım henüz tanımlanmadı."
    session_state[APPLIED_WEIGHTS_KEY] = dict(weights)
    for bucket, value in weights.items():
        session_state[draft_weight_key(bucket)] = float(value)
    return None


def clear_exposure_targets_session(session_state: Any) -> None:
    session_state.pop(APPLIED_WEIGHTS_KEY, None)
    for bucket in EXPOSURE_TARGET_BUCKETS:
        session_state[draft_weight_key(bucket)] = 0.0


def overrides_from_session(
    session_state: Optional[Mapping[str, Any]],
) -> Dict[str, Tuple[EconomicExposure, ...]]:
    raw = (session_state or {}).get(OVERRIDE_KEY) or {}
    if not isinstance(raw, Mapping):
        return {}
    overrides: Dict[str, Tuple[EconomicExposure, ...]] = {}
    for symbol, bucket in raw.items():
        key = str(bucket or "").strip().lower()
        if key not in CONFIRMABLE_BUCKETS:
            continue
        overrides[str(symbol).strip().upper()] = (
            EconomicExposure(
                exposure_bucket=key,
                weight_pct=100.0,
                evidence_source=ExposureEvidenceSource.USER_CONFIRMED,
                confidence=ExposureConfidence.HIGH,
            ),
        )
    return overrides


def set_session_override(session_state: Any, symbol: str, bucket_id: str) -> Optional[str]:
    key = str(bucket_id or "").strip().lower()
    if key not in CONFIRMABLE_BUCKETS:
        return "Bilinmiyor kullanıcı sınıflandırması olamaz."
    current = dict(session_state.get(OVERRIDE_KEY) or {})
    current[str(symbol).strip().upper()] = key
    session_state[OVERRIDE_KEY] = current
    return None


def clear_session_override(session_state: Any, symbol: str) -> None:
    current = dict(session_state.get(OVERRIDE_KEY) or {})
    current.pop(str(symbol).strip().upper(), None)
    session_state[OVERRIDE_KEY] = current


def _all_rows(view: PortfolioIntelligenceView) -> Tuple[PositionValuationRow, ...]:
    return tuple(
        [
            *view.priced_positions,
            *view.unpriced_positions,
            *view.foreign_currency_positions,
        ]
    )


def _etf_symbols(view: PortfolioIntelligenceView) -> Tuple[str, ...]:
    seen: set[str] = set()
    symbols: list[str] = []
    for row in _all_rows(view):
        symbol = str(row.symbol or "").strip().upper()
        cls = str(row.asset_class or "").strip().lower()
        if not symbol or symbol in seen:
            continue
        if cls not in {ASSET_CLASS_ETF, ASSET_CLASS_FUND}:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return tuple(symbols)


def load_persisted_fund_snapshots(
    wealth,
    symbols: Sequence[str],
) -> Dict[str, FundHoldingsSnapshotView]:
    snapshots: Dict[str, FundHoldingsSnapshotView] = {}
    client = getattr(wealth, "client", None) if wealth is not None else None
    if client is None:
        return snapshots
    from services.fund_holdings_service import FundHoldingsService

    service = FundHoldingsService(client)
    for symbol in symbols:
        try:
            snapshot = service.get_snapshot(symbol)
        except Exception:
            continue
        if snapshot is not None:
            snapshots[str(symbol).strip().upper()] = snapshot
    return snapshots


def allocation_buckets_from_exposure(
    view: PortfolioEconomicExposureView,
) -> Tuple[AllocationBucket, ...]:
    rows: list[AllocationBucket] = []
    for bucket in view.buckets:
        if not bucket.contributing_symbols and not bucket.unpriced_symbols:
            continue
        rows.append(
            AllocationBucket(
                bucket_id=bucket.bucket_id,
                dimension=AllocationDimension.ECONOMIC_EXPOSURE,
                label=EXPOSURE_BUCKET_LABELS.get(bucket.bucket_id, bucket.bucket_id),
                observable_market_value=bucket.observable_market_value,
                observable_weight_pct=bucket.observable_weight_pct,
                weight_scope=AllocationCompleteness.OBSERVABLE_ALLOCATION,
                position_count=len(bucket.contributing_symbols) + len(bucket.unpriced_symbols),
                symbols=bucket.contributing_symbols,
                unpriced_symbols=bucket.unpriced_symbols,
                valuation_complete=not bucket.unpriced_symbols,
                limitations=bucket.limitations,
            )
        )
    return tuple(rows)


def build_economic_exposure_for_ui(
    portfolio_view: PortfolioIntelligenceView,
    *,
    wealth=None,
    session_state: Optional[Any] = None,
    fund_snapshots: Optional[Mapping[str, FundHoldingsSnapshotView]] = None,
) -> PortfolioEconomicExposureView:
    snapshots = dict(fund_snapshots or {})
    if not snapshots:
        snapshots = load_persisted_fund_snapshots(wealth, _etf_symbols(portfolio_view))
    assets = wealth.list_assets() if wealth is not None else None
    positions = wealth.list_positions() if wealth is not None else None
    security_master = None
    if wealth is not None:
        from services.security_master_service import try_security_master_from_wealth

        security_master = try_security_master_from_wealth(wealth)
    return build_economic_exposure(
        portfolio_view,
        fund_snapshots=snapshots,
        user_overrides=overrides_from_session(session_state),
        assets=assets,
        positions=positions,
        security_master=security_master,
    )


def build_exposure_allocation_for_ui(
    portfolio_view: PortfolioIntelligenceView,
    exposure: PortfolioEconomicExposureView,
    *,
    wealth=None,
    session_state: Optional[Any] = None,
) -> AllocationIntelligenceView:
    policy = policy_from_exposure_session(session_state)
    amount, currency = contribution_defaults(session_state)
    conversion = _session_conversion(session_state, contribution_currency=currency)
    configured = policy_is_configured(policy)
    assets = wealth.list_assets() if wealth is not None else None
    positions = wealth.list_positions() if wealth is not None else None
    return build_allocation_intelligence(
        portfolio_view,
        policy=policy,
        contribution_amount=amount if configured else None,
        contribution_currency=currency if configured else None,
        conversion=conversion,
        assets=assets,
        positions=positions,
        exposure_buckets=allocation_buckets_from_exposure(exposure),
        exposure_view=exposure,
    )


def _instrument_class_label(instrument_class: str) -> str:
    return INSTRUMENT_CLASS_LABELS.get(str(instrument_class or "").strip().lower(), str(instrument_class or ""))


def _slice_text(slices: Sequence[PresentedExposureSlice]) -> str:
    return " · ".join(f"{format_weight_pct(row.weight_pct)} {row.label}" for row in slices)


def _instrument_evidence(instrument: InstrumentExposureView) -> str:
    if any(
        row.evidence_source == ExposureEvidenceSource.USER_CONFIRMED
        for row in instrument.economic_exposures
    ):
        return USER_CONFIRMED_LABEL
    if any(
        row.exposure_bucket == EconomicExposureBucket.UNKNOWN.value
        for row in instrument.economic_exposures
    ):
        return UNKNOWN_EVIDENCE
    sources = [row.evidence_source for row in instrument.economic_exposures]
    if not sources:
        return UNKNOWN_EVIDENCE
    return EVIDENCE_LABELS[sources[0]]


def _present_instruments(
    exposure: PortfolioEconomicExposureView,
) -> Tuple[PresentedInstrumentRow, ...]:
    rows: list[PresentedInstrumentRow] = []
    for instrument in exposure.instruments:
        slices = tuple(
            PresentedExposureSlice(
                bucket_id=row.exposure_bucket,
                label=EXPOSURE_BUCKET_LABELS.get(row.exposure_bucket, row.exposure_bucket),
                weight_pct=float(row.weight_pct),
            )
            for row in instrument.economic_exposures
        )
        unknown = any(row.bucket_id == "unknown" for row in slices)
        rows.append(
            PresentedInstrumentRow(
                symbol=instrument.symbol,
                instrument_class=_instrument_class_label(instrument.instrument_class),
                slices=slices,
                slice_text=_slice_text(slices),
                evidence=_instrument_evidence(instrument),
                user_confirmed=any(
                    row.evidence_source == ExposureEvidenceSource.USER_CONFIRMED
                    for row in instrument.economic_exposures
                ),
                valuation_available=instrument.valuation_available,
                unknown=unknown,
            )
        )
    return tuple(rows)


def _present_unknown_etfs(
    instruments: Sequence[PresentedInstrumentRow],
) -> Tuple[PresentedUnknownEtf, ...]:
    rows: list[PresentedUnknownEtf] = []
    for instrument in instruments:
        if not instrument.unknown:
            continue
        if instrument.instrument_class != "ETF":
            continue
        if instrument.user_confirmed:
            continue
        rows.append(
            PresentedUnknownEtf(
                symbol=instrument.symbol,
                instrument_class="ETF",
                economic_exposure=EXPOSURE_BUCKET_LABELS["unknown"],
                evidence=UNKNOWN_EVIDENCE,
            )
        )
    return tuple(rows)


def _present_buckets(
    exposure: PortfolioEconomicExposureView,
    allocation: AllocationIntelligenceView,
) -> Tuple[PresentedExposureBucket, ...]:
    by_id = {row.bucket_id: row for row in exposure.buckets}
    drift = {row.bucket_id: row for row in allocation.drift if row.dimension == AllocationDimension.ECONOMIC_EXPOSURE}
    rows: list[PresentedExposureBucket] = []
    for bucket_id in EXPOSURE_BUCKET_ORDER:
        bucket = by_id.get(bucket_id)
        drift_row: Optional[DriftResult] = drift.get(bucket_id)
        if bucket is None:
            continue
        if (
            not bucket.contributing_symbols
            and not bucket.unpriced_symbols
            and drift_row is None
        ):
            continue
        limitation = None
        if bucket.unpriced_symbols:
            limitation = (
                f"Kısmi değerleme — değerlenemeyen: {', '.join(bucket.unpriced_symbols)}. "
                "Bu kova %0 sayılmaz."
            )
        elif bucket_id == "unknown" and bucket.contributing_symbols:
            limitation = "Ekonomik maruziyet sınıflandırılamadı; look-through yok."
        status = drift_row.status if drift_row else None
        rows.append(
            PresentedExposureBucket(
                bucket_id=bucket_id,
                label=EXPOSURE_BUCKET_LABELS.get(bucket_id, bucket_id),
                observable_weight_pct=bucket.observable_weight_pct,
                target_weight_pct=None if drift_row is None else drift_row.target_weight_pct,
                drift_pct=None if drift_row is None else drift_row.drift_pct,
                status_label=STATUS_LABELS.get(status) if status else None,
                status_tone=STATUS_TONES.get(status, "neutral") if status else "neutral",
                indeterminate=status == DriftStatus.INDETERMINATE,
                unpriced_symbols=bucket.unpriced_symbols,
                contributing_symbols=bucket.contributing_symbols,
                limitation=limitation,
            )
        )
    return tuple(rows)


def _present_routing(allocation: AllocationIntelligenceView) -> PresentedExposureRouting:
    route = next(
        (row for row in allocation.routing if row.dimension == AllocationDimension.ECONOMIC_EXPOSURE),
        allocation.routing[0] if allocation.routing else None,
    )
    if route is None or route.status == RoutingStatus.TARGET_NOT_CONFIGURED:
        return PresentedExposureRouting(
            message=UNCONFIGURED_ROUTING,
            status=RoutingStatus.TARGET_NOT_CONFIGURED.value,
            best_bucket_label=None,
            before_drift=None,
            after_drift=None,
            improvement=None,
            evidence_quality=None,
            limitation=None,
        )
    if route.status == RoutingStatus.FX_REQUIRED:
        return PresentedExposureRouting(
            message=FX_REQUIRED_COPY,
            status=route.status.value,
            best_bucket_label=None,
            before_drift=None,
            after_drift=None,
            improvement=None,
            evidence_quality=EVIDENCE_QUALITY_LABELS.get(route.evidence_quality),
            limitation=FX_REQUIRED_COPY,
        )
    if route.status in {RoutingStatus.INDETERMINATE, RoutingStatus.UNAVAILABLE}:
        return PresentedExposureRouting(
            message=(
                INDETERMINATE_EXPOSURE_ROUTING
                if "EXPOSURE_CLASSIFICATION_INCOMPLETE" in route.limitations
                or route.status == RoutingStatus.INDETERMINATE
                else UNCONFIGURED_ROUTING
            ),
            status=route.status.value,
            best_bucket_label=None,
            before_drift=route.before_drift_score,
            after_drift=None,
            improvement=None,
            evidence_quality=EVIDENCE_QUALITY_LABELS.get(route.evidence_quality),
            limitation=INDETERMINATE_EXPOSURE_ROUTING,
        )
    label = EXPOSURE_BUCKET_LABELS.get(route.best_bucket_id or "", route.best_bucket_id)
    return PresentedExposureRouting(
        message=(
            f"Ekonomik maruziyet hedefinize göre {label} bölgesine yönlendirme "
            "ölçülebilir sapmayı azaltıyor."
        ),
        status=route.status.value,
        best_bucket_label=label,
        before_drift=route.before_drift_score,
        after_drift=route.after_drift_score,
        improvement=route.improvement,
        evidence_quality=EVIDENCE_QUALITY_LABELS.get(route.evidence_quality),
        limitation=None,
    )


def present_economic_exposure_center(
    exposure: PortfolioEconomicExposureView,
    allocation: AllocationIntelligenceView,
    *,
    draft_weights: Optional[Mapping[str, float]] = None,
    persisted: bool = False,
    persistence_message: Optional[str] = None,
) -> EconomicExposurePresentation:
    draft = dict(draft_weights or {})
    total = sum(float(draft.get(bucket, 0.0)) for bucket in EXPOSURE_TARGET_BUCKETS)
    remaining = remaining_target_pct(draft)
    has_draft = any(float(draft.get(bucket, 0.0)) for bucket in EXPOSURE_TARGET_BUCKETS)
    apply_error = (
        validate_exposure_target_weights(draft)
        if has_draft
        else "Hedef dağılım henüz tanımlanmadı."
    )
    instruments = _present_instruments(exposure)
    unknown_etfs = _present_unknown_etfs(instruments)
    buckets = _present_buckets(exposure, allocation)
    incomplete = bool(unknown_etfs) or any(row.indeterminate for row in buckets)
    growth = is_growth_economic_exposure_weights(draft) and (
        persisted or allocation.target_policy_status == AllocationPolicyStatus.CONFIGURED
    )
    note = GROWTH_TARGET_LABEL if growth else SESSION_TARGET_NOTE
    return EconomicExposurePresentation(
        heading=HEADING,
        view_asset_class_label=DIMENSION_LABELS[VIEW_ASSET_CLASS],
        view_economic_label=DIMENSION_LABELS[VIEW_ECONOMIC_EXPOSURE],
        valuation_coverage_label=VALUATION_COVERAGE_LABEL,
        valuation_coverage_pct=float(exposure.valuation_coverage_pct),
        classification_coverage_label=CLASSIFICATION_COVERAGE_LABEL,
        classification_coverage_pct=float(exposure.exposure_classification_coverage_pct),
        unknown_etf_heading=UNKNOWN_ETF_HEADING,
        user_confirmed_label=USER_CONFIRMED_LABEL,
        session_target_note=note,
        remaining_pct=remaining,
        draft_total=round(total, 4),
        can_apply=apply_error is None,
        apply_error=None if apply_error is None else apply_error,
        configured=allocation.target_policy_status == AllocationPolicyStatus.CONFIGURED,
        buckets=buckets,
        instruments=instruments,
        unknown_etfs=unknown_etfs,
        routing=_present_routing(allocation),
        persisted=bool(persisted),
        growth_label=GROWTH_TARGET_LABEL if growth else None,
        incomplete_note=INCOMPLETE_DRIFT_NOTE if incomplete else None,
        persistence_message=persistence_message,
    )


def flatten_economic_exposure_text(presented: EconomicExposurePresentation) -> str:
    parts = [
        presented.heading,
        presented.view_asset_class_label,
        presented.view_economic_label,
        presented.valuation_coverage_label,
        format_weight_pct(presented.valuation_coverage_pct) or "",
        presented.classification_coverage_label,
        format_weight_pct(presented.classification_coverage_pct) or "",
        presented.unknown_etf_heading,
        presented.user_confirmed_label,
        presented.session_target_note,
        presented.growth_label or "",
        presented.incomplete_note or "",
        presented.persistence_message or "",
        PERSISTED_STATUS if presented.persisted else "",
        presented.routing.message,
        presented.apply_error or "",
        presented.routing.best_bucket_label or "",
        presented.routing.limitation or "",
    ]
    for row in presented.buckets:
        parts.extend(
            [
                row.label,
                row.status_label or "",
                row.limitation or "",
                format_weight_pct(row.observable_weight_pct) or "",
            ]
        )
    for row in presented.instruments:
        parts.extend(
            [
                row.symbol,
                row.instrument_class,
                row.slice_text,
                row.evidence,
            ]
        )
    for row in presented.unknown_etfs:
        parts.extend(
            [
                row.symbol,
                row.instrument_class,
                row.economic_exposure,
                row.evidence,
            ]
        )
    return "\n".join(part for part in parts if part)


def _confirmable_unknown_symbols(presented: EconomicExposurePresentation) -> Tuple[str, ...]:
    return tuple(row.symbol for row in presented.unknown_etfs)


def _render_economic_presented(
    presented: EconomicExposurePresentation,
    *,
    session_state,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> None:
    import streamlit as st

    render_section_title(presented.heading)
    if presented.growth_label:
        st.caption(presented.growth_label)
    else:
        st.caption(presented.session_target_note)
    if presented.persisted and not presented.growth_label:
        st.caption(PERSISTED_STATUS)
    if presented.incomplete_note:
        st.caption(presented.incomplete_note)
    coverage = st.columns(2)
    with coverage[0]:
        st.caption(presented.valuation_coverage_label)
        st.markdown(f"**{format_weight_pct(presented.valuation_coverage_pct)}**")
    with coverage[1]:
        st.caption(presented.classification_coverage_label)
        st.markdown(f"**{format_weight_pct(presented.classification_coverage_pct)}**")
    cols = st.columns(len(EXPOSURE_TARGET_BUCKETS))
    for col, bucket in zip(cols, EXPOSURE_TARGET_BUCKETS):
        with col:
            st.number_input(
                EXPOSURE_BUCKET_LABELS[bucket],
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                key=draft_weight_key(bucket),
                help="Yüzde; toplam 100 olmalı. Otomatik dengeleme yok.",
            )
    remaining = remaining_target_pct(draft_weights_from_session(session_state))
    if abs(remaining) <= TARGET_SUM_EPSILON_PCT:
        st.caption("Toplam 100%.")
    elif remaining > 0:
        st.caption(f"Kalan: {remaining:.1f}%")
    else:
        st.caption(f"Fazla tahsis: {abs(remaining):.1f}% — otomatik dengeleme yok.")
    actions = st.columns(2)
    with actions[0]:
        if st.button(SAVE_LABEL, disabled=not presented.can_apply, key="economic_exposure_save"):
            error = save_economic_exposure_policy_from_session(
                session_state,
                policy_service=policy_service,
                portfolio_id=portfolio_id,
            )
            if error:
                session_state[SAVE_ERROR_KEY] = error
            else:
                st.rerun()
    with actions[1]:
        if st.button(RESET_LABEL, key="economic_exposure_reset"):
            error = reset_economic_exposure_policy_session(
                session_state,
                policy_service=policy_service,
                portfolio_id=portfolio_id,
            )
            if error:
                session_state[RESET_ERROR_KEY] = error
            else:
                st.rerun()
    save_error = session_state.get(SAVE_ERROR_KEY) or session_state.get(RESET_ERROR_KEY)
    if save_error:
        st.info(save_error)
    elif presented.apply_error and not presented.configured:
        st.info(presented.apply_error)
    render_section_title("Ölçülebilir Ekonomik Maruziyet")
    for row in presented.buckets:
        status = ""
        if row.status_label:
            if row.indeterminate:
                status = render_status_badge("Belirsiz", "info")
            else:
                status = render_status_badge(row.status_label, row.status_tone)
        observable = format_weight_pct(row.observable_weight_pct) or "ölçülemedi"
        target = format_weight_pct(row.target_weight_pct) or "—"
        drift = (
            format_weight_pct(row.drift_pct)
            if row.drift_pct is not None and not row.indeterminate
            else "—"
        )
        st.markdown(
            f"**{row.label}** · Ölçülebilir {observable} · Hedef {target} · Sapma {drift} {status}",
            unsafe_allow_html=True,
        )
        if row.limitation:
            st.caption(row.limitation)
    if presented.unknown_etfs:
        render_section_title(presented.unknown_etf_heading)
        for row in presented.unknown_etfs:
            st.markdown(
                f"**{row.symbol}** · varlık türü {row.instrument_class} · "
                f"ekonomik maruziyet {row.economic_exposure} · kanıt {row.evidence}"
            )
    confirmable = _confirmable_unknown_symbols(presented)
    if confirmable:
        render_section_title(presented.user_confirmed_label)
        st.caption("Yalnızca sınıflandırılamayan araçlar. Oturumda kalır; kaydedilmez.")
        selected = st.selectbox(
            "Araç",
            options=list(confirmable),
            key="economic_exposure_override_symbol",
        )
        bucket = st.selectbox(
            "Ekonomik maruziyet",
            options=list(CONFIRMABLE_BUCKETS),
            format_func=lambda value: EXPOSURE_BUCKET_LABELS[value],
            key="economic_exposure_override_bucket",
        )
        confirm_cols = st.columns(2)
        with confirm_cols[0]:
            if st.button(USER_CONFIRMED_LABEL, key="economic_exposure_override_confirm"):
                error = set_session_override(session_state, str(selected), str(bucket))
                if error:
                    st.info(error)
                else:
                    st.rerun()
        with confirm_cols[1]:
            if st.button("Sınıflandırmayı temizle", key="economic_exposure_override_clear"):
                clear_session_override(session_state, str(selected))
                st.rerun()
    confirmed = [row for row in presented.instruments if row.user_confirmed]
    for row in confirmed:
        st.caption(
            f"{row.symbol}: {row.slice_text} · {presented.user_confirmed_label}"
        )
    render_section_title("Yeni katkıyı nereye yönlendirmek dengeyi iyileştirir?")
    st.caption(SIMULATION_NOTE)
    amount, currency = contribution_defaults(session_state)
    if CONTRIB_AMOUNT_KEY not in session_state:
        session_state[CONTRIB_AMOUNT_KEY] = float(amount)
    if CONTRIB_CURRENCY_KEY not in session_state:
        session_state[CONTRIB_CURRENCY_KEY] = currency
    inputs = st.columns(2)
    with inputs[0]:
        st.number_input(
            PLANNED_CONTRIBUTION_LABEL,
            min_value=0.0,
            step=100.0,
            key=CONTRIB_AMOUNT_KEY,
        )
    with inputs[1]:
        st.selectbox(
            "Katkı para birimi",
            options=["TRY", "USD"],
            key=CONTRIB_CURRENCY_KEY,
        )
    st.caption(presented.routing.message)
    if presented.routing.best_bucket_label and presented.routing.status == RoutingStatus.AVAILABLE.value:
        st.caption(
            f"Sapma skoru: {presented.routing.before_drift} → {presented.routing.after_drift} "
            f"(iyileşme {presented.routing.improvement})"
        )
        if presented.routing.evidence_quality:
            st.caption(f"Kanıt: {presented.routing.evidence_quality}")
        if presented.routing.limitation:
            st.caption(presented.routing.limitation)


def render_economic_exposure_center(
    *,
    portfolio_view: PortfolioIntelligenceView,
    wealth=None,
    session_state,
    fund_snapshots: Optional[Mapping[str, FundHoldingsSnapshotView]] = None,
    policy_service=None,
    portfolio_id: Optional[str] = None,
) -> EconomicExposurePresentation:
    exposure = build_economic_exposure_for_ui(
        portfolio_view,
        wealth=wealth,
        session_state=session_state,
        fund_snapshots=fund_snapshots,
    )
    allocation = build_exposure_allocation_for_ui(
        portfolio_view,
        exposure,
        wealth=wealth,
        session_state=session_state,
    )
    persisted = bool(session_state.get(PERSISTED_FLAG_KEY))
    persistence_message = session_state.get(SAVE_ERROR_KEY) or session_state.get(RESET_ERROR_KEY)
    presented = present_economic_exposure_center(
        exposure,
        allocation,
        draft_weights=draft_weights_from_session(session_state),
        persisted=persisted,
        persistence_message=persistence_message,
    )
    _render_economic_presented(
        presented,
        session_state=session_state,
        policy_service=policy_service,
        portfolio_id=portfolio_id,
    )
    return presented
