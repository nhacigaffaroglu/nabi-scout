"""Diagnostic-only hybrid exposure facts. Does not allocate or classify UNKNOWN.

Shadow statuses stay 7F math. Ceiling candidates are evaluated here only;
nothing is activated. Live New Money still uses production DriftStatus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from config.participation_catalog import configured_participation_for_symbol
from services.layer_exposure_determinacy import (
    WEIGHT_QUANT,
    ExposureDeterminacyView,
    LayerExposureDeterminacy,
    ShadowEvaluationMode,
)
from services.participation_filter_service import (
    PARTICIPATION_UNKNOWN,
    normalize_participation_status,
)
from services.participation_intelligence_contract import PARTICIPATION_STATUS_UYGUN

UNKNOWN_BUCKET = "unknown"

CEILING_CANDIDATES_PCT = (0.25, 0.50, 1.00, 2.00, 3.00, 5.00, 10.00)
ABSOLUTE_GUARD_CANDIDATES = (None, 100.0, 500.0, 1000.0, 5000.0, 10000.0)

LIVE_BLOCKER_INCOMPLETE = "EXPOSURE_CLASSIFICATION_INCOMPLETE"
SHADOW_BLOCKER_UNSAFE = "PORTFOLIO_EXPOSURE_UNSAFE"
SHADOW_BLOCKER_NO_UW = "NO_ROBUST_UNDERWEIGHT_LAYER"
SHADOW_BLOCKER_NO_FILL = "NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER"
HYBRID_ALLOCATION_ACTIVE = False

# Future hybrid activation order. Live production is still LIVE_BLOCKER_INCOMPLETE.
HYBRID_BLOCKER_PRECEDENCE = (
    SHADOW_BLOCKER_UNSAFE,
    SHADOW_BLOCKER_NO_UW,
    SHADOW_BLOCKER_NO_FILL,
    "PARTICIPATION_BLOCKED",
    "CONCENTRATION_BLOCKED",
    "TRANSACTION_EFFICIENCY_BLOCKED",
)

# Mix-maintenance is not activated. Recommended future policy is recorded only.
MIX_MAINTENANCE_RECOMMENDATION = "OPTION_C_U0_ONLY"


def _round(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), WEIGHT_QUANT)


def _classified_layers(instrument: Any) -> Tuple[str, ...]:
    layers: list[str] = []
    for row in getattr(instrument, "economic_exposures", ()) or ():
        bucket = str(getattr(row, "exposure_bucket", "") or "").strip().lower()
        if not bucket or bucket == UNKNOWN_BUCKET:
            continue
        if float(getattr(row, "weight_pct", 0) or 0) <= 0:
            continue
        if bucket not in layers:
            layers.append(bucket)
    return tuple(layers)


def _resolve_participation(
    symbol: str,
    *,
    candidate: Optional[Mapping[str, Any]] = None,
    asset: Optional[Mapping[str, Any]] = None,
) -> str:
    if candidate is not None:
        status = normalize_participation_status(candidate.get("participation_status"))
        if status != PARTICIPATION_UNKNOWN:
            return status
    if asset is not None:
        status = normalize_participation_status(asset.get("participation_status"))
        if status != PARTICIPATION_UNKNOWN:
            return status
    catalog = configured_participation_for_symbol(symbol)
    if catalog is not None:
        return normalize_participation_status(catalog[0])
    return PARTICIPATION_UNKNOWN


@dataclass(frozen=True)
class UnknownContributor:
    symbol: str
    unknown_weight_pct: float
    unknown_market_value: float
    lot_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "unknown_weight_pct": self.unknown_weight_pct,
            "unknown_market_value": self.unknown_market_value,
            "lot_count": self.lot_count,
        }


@dataclass(frozen=True)
class LayerDiagnostic:
    layer: str
    target_pct: Optional[float]
    known_pct: Optional[float]
    min_pct: Optional[float]
    max_pct: Optional[float]
    lower_bound_pct: Optional[float]
    upper_bound_pct: Optional[float]
    production_status: Optional[str]
    robust_status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "target_pct": self.target_pct,
            "known_pct": self.known_pct,
            "min_pct": self.min_pct,
            "max_pct": self.max_pct,
            "lower_bound_pct": self.lower_bound_pct,
            "upper_bound_pct": self.upper_bound_pct,
            "production_status": self.production_status,
            "robust_status": self.robust_status,
        }


@dataclass(frozen=True)
class FillAsset:
    symbol: str
    layers: Tuple[str, ...]
    participation_status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "layers": list(self.layers),
            "participation_status": self.participation_status,
        }


@dataclass(frozen=True)
class ExposureDiagnosticsView:
    evaluation_mode: str
    classification_complete: bool
    known_pct: Optional[float]
    unknown_pct: Optional[float]
    unknown_market_value: Optional[float]
    production_completeness: str
    hybrid_allocation_active: bool
    layers: Tuple[LayerDiagnostic, ...]
    unknown_contributors: Tuple[UnknownContributor, ...]
    robust_underweight_layers: Tuple[str, ...]
    fillable_robust_underweight_layers: Tuple[str, ...]
    unfillable_robust_underweight_layers: Tuple[str, ...]
    eligible_fill_assets: Tuple[FillAsset, ...]
    live_blocker: Optional[str]
    shadow_next_blocker: Optional[str]
    reason_codes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_mode": self.evaluation_mode,
            "classification_complete": self.classification_complete,
            "known_pct": self.known_pct,
            "unknown_pct": self.unknown_pct,
            "unknown_market_value": self.unknown_market_value,
            "production_completeness": self.production_completeness,
            "hybrid_allocation_active": self.hybrid_allocation_active,
            "layers": [row.to_dict() for row in self.layers],
            "unknown_contributors": [row.to_dict() for row in self.unknown_contributors],
            "robust_underweight_layers": list(self.robust_underweight_layers),
            "fillable_robust_underweight_layers": list(self.fillable_robust_underweight_layers),
            "unfillable_robust_underweight_layers": list(self.unfillable_robust_underweight_layers),
            "eligible_fill_assets": [row.to_dict() for row in self.eligible_fill_assets],
            "live_blocker": self.live_blocker,
            "shadow_next_blocker": self.shadow_next_blocker,
            "reason_codes": list(self.reason_codes),
        }

    def to_adviser_dict(self, *, new_money: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "production_completeness": self.production_completeness,
            "shadow_evaluation": self.evaluation_mode,
            "classification_complete": self.classification_complete,
            "known_pct": self.known_pct,
            "unknown_pct": self.unknown_pct,
            "unknown_market_value": self.unknown_market_value,
            "unknown_contributors": [row.to_dict() for row in self.unknown_contributors],
            "hybrid_allocation_active": False,
            "layers": [row.to_dict() for row in self.layers],
            "new_money": {
                "allocated": None if new_money is None else new_money.get("total_allocated"),
                "residual": None if new_money is None else new_money.get("residual_cash"),
                "production_blocker": self.live_blocker,
                "robust_underweight_layers": list(self.robust_underweight_layers),
                "fillable_robust_underweight_layers": list(self.fillable_robust_underweight_layers),
                "unfillable_robust_underweight_layers": list(
                    self.unfillable_robust_underweight_layers
                ),
                "shadow_next_blocker": self.shadow_next_blocker,
            },
        }
        return payload


def unknown_contributors_from_exposure(
    exposure: Any,
) -> Tuple[UnknownContributor, ...]:
    priced = float(exposure.observable_total_market_value or 0.0)
    lots: Dict[str, list[float]] = {}
    for instrument in exposure.instruments:
        symbol = str(instrument.symbol or "").strip().upper()
        if not symbol:
            continue
        mv = float(instrument.observable_market_value or 0.0)
        unknown_weight = sum(
            float(row.weight_pct or 0.0)
            for row in instrument.economic_exposures
            if row.exposure_bucket == UNKNOWN_BUCKET
        )
        if unknown_weight <= 0 or mv <= 0:
            continue
        lots.setdefault(symbol, []).append(mv * unknown_weight / 100.0)
    rows: list[UnknownContributor] = []
    for symbol, values in lots.items():
        unknown_mv = _round(sum(values)) or 0.0
        weight = _round((unknown_mv / priced) * 100.0) if priced > 0 else 0.0
        rows.append(
            UnknownContributor(
                symbol=symbol,
                unknown_weight_pct=float(weight or 0.0),
                unknown_market_value=unknown_mv,
                lot_count=len(values),
            )
        )
    return tuple(sorted(rows, key=lambda row: (-row.unknown_weight_pct, row.symbol)))


def ceiling_allows_bound_evaluation(
    unknown_pct: Any,
    max_unknown_portfolio_pct: Optional[float],
) -> Optional[bool]:
    """Inclusive eligibility only. None ceiling means not evaluated (shadow diagnostic)."""
    if max_unknown_portfolio_pct is None:
        return None
    try:
        unknown = float(unknown_pct)
        ceiling = float(max_unknown_portfolio_pct)
    except (TypeError, ValueError):
        return False
    if unknown < 0 or ceiling < 0:
        return False
    return unknown <= ceiling


def absolute_guard_allows(
    unknown_market_value: Any,
    max_unknown_absolute_value: Optional[float],
) -> Optional[bool]:
    if max_unknown_absolute_value is None:
        return None
    try:
        unknown_mv = float(unknown_market_value)
        ceiling = float(max_unknown_absolute_value)
    except (TypeError, ValueError):
        return False
    if unknown_mv < 0 or ceiling < 0:
        return False
    return unknown_mv <= ceiling


def combined_guard_unsafe(
    *,
    percent_allows: Optional[bool],
    absolute_allows: Optional[bool],
    mode: str = "OR",
) -> bool:
    """True when the book is unsafe. OR = fail if either supplied guard fails."""
    checks = [item for item in (percent_allows, absolute_allows) if item is not None]
    if not checks:
        return False
    if mode == "AND":
        return not all(checks)
    return any(item is False for item in checks)


def evaluate_ceiling_candidates(
    unknown_pct: float,
    *,
    candidates: Sequence[float] = CEILING_CANDIDATES_PCT,
) -> Tuple[Tuple[float, bool], ...]:
    return tuple(
        (float(ceiling), bool(ceiling_allows_bound_evaluation(unknown_pct, ceiling)))
        for ceiling in candidates
    )


def shadow_next_blocker(
    *,
    robust_underweight: Sequence[str],
    fillable: Sequence[str],
    ceiling_allows: Optional[bool] = None,
) -> Optional[str]:
    if ceiling_allows is False:
        return SHADOW_BLOCKER_UNSAFE
    if not robust_underweight:
        return SHADOW_BLOCKER_NO_UW
    unfilled = [layer for layer in robust_underweight if layer not in set(fillable)]
    if unfilled:
        return f"{SHADOW_BLOCKER_NO_FILL}:{unfilled[0]}"
    return None


def _unknown_market_value(exposure: Any) -> Optional[float]:
    unknown = next(
        (row for row in exposure.buckets if row.bucket_id == UNKNOWN_BUCKET),
        None,
    )
    if unknown is None:
        return 0.0
    return _round(float(unknown.observable_market_value or 0.0))


def eligible_fill_assets(
    instruments: Sequence[Any],
    *,
    extra_symbols: Sequence[Mapping[str, Any]] = (),
    assets: Sequence[Mapping[str, Any]] = (),
) -> Tuple[FillAsset, ...]:
    """Participation-Uygun instruments only. Layers come from classified sleeves."""
    asset_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row for row in assets if row.get("symbol")
    }
    extra_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row
        for row in extra_symbols
        if str(row.get("symbol") or "").strip()
    }
    seen: set[str] = set()
    rows: list[FillAsset] = []
    for instrument in instruments:
        symbol = str(getattr(instrument, "symbol", "") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        status = _resolve_participation(
            symbol,
            candidate=extra_by_symbol.get(symbol),
            asset=asset_by_symbol.get(symbol),
        )
        if normalize_participation_status(status) != PARTICIPATION_STATUS_UYGUN:
            continue
        layers = _classified_layers(instrument)
        rows.append(FillAsset(symbol=symbol, layers=layers, participation_status=status))
    for symbol, raw in sorted(extra_by_symbol.items()):
        if symbol in seen:
            continue
        status = _resolve_participation(symbol, candidate=raw, asset=asset_by_symbol.get(symbol))
        if normalize_participation_status(status) != PARTICIPATION_STATUS_UYGUN:
            continue
        instrument = next(
            (
                row
                for row in instruments
                if str(getattr(row, "symbol", "") or "").strip().upper() == symbol
            ),
            None,
        )
        layers = _classified_layers(instrument) if instrument is not None else ()
        rows.append(FillAsset(symbol=symbol, layers=layers, participation_status=status))
        seen.add(symbol)
    return tuple(rows)


def build_exposure_diagnostics(
    *,
    exposure: Optional[Any],
    determinacy: Optional[ExposureDeterminacyView],
    production_drift: Sequence[Any] = (),
    production_limitations: Sequence[str] = (),
    fill_assets: Sequence[FillAsset] = (),
    ceiling_allows: Optional[bool] = None,
) -> ExposureDiagnosticsView:
    live = (
        LIVE_BLOCKER_INCOMPLETE
        if LIVE_BLOCKER_INCOMPLETE in {str(item) for item in production_limitations}
        else None
    )
    if exposure is None or determinacy is None:
        return ExposureDiagnosticsView(
            evaluation_mode=ShadowEvaluationMode.UNAVAILABLE.value,
            classification_complete=False,
            known_pct=None,
            unknown_pct=None,
            unknown_market_value=None,
            production_completeness="UNAVAILABLE",
            hybrid_allocation_active=HYBRID_ALLOCATION_ACTIVE,
            layers=(),
            unknown_contributors=(),
            robust_underweight_layers=(),
            fillable_robust_underweight_layers=(),
            unfillable_robust_underweight_layers=(),
            eligible_fill_assets=tuple(fill_assets),
            live_blocker=live,
            shadow_next_blocker=SHADOW_BLOCKER_NO_UW,
            reason_codes=("DIAGNOSTICS_UNAVAILABLE",),
        )

    drift_by_layer = {}
    for row in production_drift:
        dimension = getattr(row, "dimension", None)
        value = getattr(dimension, "value", dimension)
        if value not in {None, "ECONOMIC_EXPOSURE"}:
            continue
        drift_by_layer[str(getattr(row, "bucket_id", "")).strip().lower()] = getattr(
            getattr(row, "status", None), "value", getattr(row, "status", None)
        )

    layers = tuple(
        LayerDiagnostic(
            layer=item.layer,
            target_pct=item.target_pct,
            known_pct=item.known_pct,
            min_pct=item.min_pct,
            max_pct=item.max_pct,
            lower_bound_pct=item.lower_bound_pct,
            upper_bound_pct=item.upper_bound_pct,
            production_status=drift_by_layer.get(item.layer),
            robust_status=item.status.value,
        )
        for item in determinacy.layers
    )
    robust_uw = tuple(
        item.layer
        for item in determinacy.layers
        if item.status == LayerExposureDeterminacy.ROBUST_UNDERWEIGHT
    )
    fill_by_layer: Dict[str, list[str]] = {}
    for asset in fill_assets:
        for layer in asset.layers:
            fill_by_layer.setdefault(layer, []).append(asset.symbol)
    fillable = tuple(layer for layer in robust_uw if fill_by_layer.get(layer))
    unfillable = tuple(layer for layer in robust_uw if layer not in set(fillable))
    completeness = (
        "COMPLETE_EXPOSURE"
        if determinacy.classification_complete
        else str(getattr(exposure.completeness, "value", exposure.completeness) or "PARTIAL_EXPOSURE")
    )
    return ExposureDiagnosticsView(
        evaluation_mode=determinacy.evaluation_mode.value,
        classification_complete=determinacy.classification_complete,
        known_pct=determinacy.known_pct,
        unknown_pct=determinacy.unknown_pct,
        unknown_market_value=_unknown_market_value(exposure),
        production_completeness=completeness,
        hybrid_allocation_active=False,
        layers=layers,
        unknown_contributors=unknown_contributors_from_exposure(exposure),
        robust_underweight_layers=robust_uw,
        fillable_robust_underweight_layers=fillable,
        unfillable_robust_underweight_layers=unfillable,
        eligible_fill_assets=tuple(fill_assets),
        live_blocker=live,
        shadow_next_blocker=shadow_next_blocker(
            robust_underweight=robust_uw,
            fillable=fillable,
            ceiling_allows=ceiling_allows,
        ),
        reason_codes=determinacy.reason_codes,
    )


def calibrate_book(
    *,
    unknown_pct: float,
    known_by_layer: Mapping[str, float],
    targets: Sequence[Tuple[str, float]],
    tolerance_pct: float,
    simple_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """Pure calibration case. Does not mutate production completeness."""
    from services.layer_exposure_determinacy import assess_economic_exposure_determinacy

    view = assess_economic_exposure_determinacy(
        targets=targets,
        known_by_layer=known_by_layer,
        unknown_pct=unknown_pct,
        tolerance_pct=tolerance_pct,
        valuation_complete=True,
        unpriced=False,
        max_unknown_portfolio_pct=None,
    )
    statuses = {row.layer: row.status.value for row in view.layers}
    ambiguous = [layer for layer, status in statuses.items() if status == "AMBIGUOUS"]
    robust = [layer for layer, status in statuses.items() if status.startswith("ROBUST_")]
    robust_uw = [layer for layer, status in statuses.items() if status == "ROBUST_UNDERWEIGHT"]
    simple_complete = simple_threshold is not None and unknown_pct <= simple_threshold
    simple_false_safe = bool(simple_complete and ambiguous)
    return {
        "unknown_pct": unknown_pct,
        "statuses": statuses,
        "robust_count": len(robust),
        "ambiguous_count": len(ambiguous),
        "robust_underweight": robust_uw,
        "has_robust_underweight": bool(robust_uw),
        "simple_threshold_complete": simple_complete,
        "simple_threshold_false_safe": simple_false_safe,
        "strict_blocks": unknown_pct > 0,
    }


def empty_exposure_diagnostics(*, live_blocker: Optional[str] = None) -> ExposureDiagnosticsView:
    return ExposureDiagnosticsView(
        evaluation_mode=ShadowEvaluationMode.UNAVAILABLE.value,
        classification_complete=False,
        known_pct=None,
        unknown_pct=None,
        unknown_market_value=None,
        production_completeness="UNAVAILABLE",
        hybrid_allocation_active=False,
        layers=(),
        unknown_contributors=(),
        robust_underweight_layers=(),
        fillable_robust_underweight_layers=(),
        unfillable_robust_underweight_layers=(),
        eligible_fill_assets=(),
        live_blocker=live_blocker,
        shadow_next_blocker=None,
        reason_codes=("EXPOSURE_NOT_REQUESTED",),
    )
