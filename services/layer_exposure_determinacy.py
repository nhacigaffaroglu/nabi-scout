"""Shadow economic-exposure layer determinacy. Pure, side-effect free.

Does not classify UNKNOWN. Does not change production DriftStatus.
Ceiling application is not activated; max_unknown_portfolio_pct is accepted
for a future caller and ignored in 7F diagnostic mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

WEIGHT_QUANT = 4
MASS_OVERFLOW_REASON = "MASS_OVERFLOW_OBSERVED"
EVALUATION_MODE_SHADOW = "SHADOW_EVALUATED"


class LayerExposureDeterminacy(str, Enum):
    ROBUST_UNDERWEIGHT = "ROBUST_UNDERWEIGHT"
    ROBUST_ON_TARGET = "ROBUST_ON_TARGET"
    ROBUST_OVERWEIGHT = "ROBUST_OVERWEIGHT"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"


class ShadowEvaluationMode(str, Enum):
    SHADOW_EVALUATED = "SHADOW_EVALUATED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class LayerUncertaintyAssessment:
    layer: str
    known_pct: Optional[float]
    unknown_pct: Optional[float]
    target_pct: Optional[float]
    tolerance_pct: Optional[float]
    min_pct: Optional[float]
    max_pct: Optional[float]
    lower_bound_pct: Optional[float]
    upper_bound_pct: Optional[float]
    status: LayerExposureDeterminacy
    reason_codes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer,
            "known_pct": self.known_pct,
            "unknown_pct": self.unknown_pct,
            "target_pct": self.target_pct,
            "tolerance_pct": self.tolerance_pct,
            "min_pct": self.min_pct,
            "max_pct": self.max_pct,
            "lower_bound_pct": self.lower_bound_pct,
            "upper_bound_pct": self.upper_bound_pct,
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class ExposureDeterminacyView:
    evaluation_mode: ShadowEvaluationMode
    classification_complete: bool
    known_pct: Optional[float]
    unknown_pct: Optional[float]
    layers: Tuple[LayerUncertaintyAssessment, ...]
    reason_codes: Tuple[str, ...] = ()
    max_unknown_portfolio_pct: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_mode": self.evaluation_mode.value,
            "classification_complete": self.classification_complete,
            "known_pct": self.known_pct,
            "unknown_pct": self.unknown_pct,
            "layers": [row.to_dict() for row in self.layers],
            "reason_codes": list(self.reason_codes),
            "max_unknown_portfolio_pct": self.max_unknown_portfolio_pct,
        }


def _round(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), WEIGHT_QUANT)


def _is_finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _invalid_scalar_reasons(
    *,
    known_pct: Any,
    unknown_pct: Any,
    target_pct: Any,
    tolerance_pct: Any,
) -> Tuple[str, ...]:
    reasons: list[str] = []
    checks = (
        ("known_pct", known_pct, "INVALID_KNOWN"),
        ("unknown_pct", unknown_pct, "INVALID_UNKNOWN"),
        ("target_pct", target_pct, "INVALID_TARGET"),
        ("tolerance_pct", tolerance_pct, "INVALID_TOLERANCE"),
    )
    for _name, raw, code in checks:
        if not _is_finite_number(raw):
            reasons.append(code)
            continue
        number = float(raw)
        if number < 0:
            reasons.append(code)
    if _is_finite_number(unknown_pct) and float(unknown_pct) > 100:
        reasons.append("UNKNOWN_EXCEEDS_100")
    return tuple(dict.fromkeys(reasons))


def _unavailable(
    layer: str,
    *,
    known_pct: Optional[float] = None,
    unknown_pct: Optional[float] = None,
    target_pct: Optional[float] = None,
    tolerance_pct: Optional[float] = None,
    reason_codes: Sequence[str],
) -> LayerUncertaintyAssessment:
    return LayerUncertaintyAssessment(
        layer=layer,
        known_pct=_round(known_pct) if known_pct is not None and _is_finite_number(known_pct) else None,
        unknown_pct=_round(unknown_pct) if unknown_pct is not None and _is_finite_number(unknown_pct) else None,
        target_pct=_round(target_pct) if target_pct is not None and _is_finite_number(target_pct) else None,
        tolerance_pct=_round(tolerance_pct)
        if tolerance_pct is not None and _is_finite_number(tolerance_pct)
        else None,
        min_pct=None,
        max_pct=None,
        lower_bound_pct=None,
        upper_bound_pct=None,
        status=LayerExposureDeterminacy.UNAVAILABLE,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def assess_layer_uncertainty(
    *,
    layer: str,
    known_pct: Any,
    unknown_pct: Any,
    target_pct: Any,
    tolerance_pct: Any,
    valuation_available: bool = True,
) -> LayerUncertaintyAssessment:
    """Independent conservative [MIN, MAX] = [K, K+U]. UNKNOWN is not assigned."""
    if not str(layer or "").strip():
        return _unavailable("", reason_codes=("MISSING_LAYER",))
    if not valuation_available:
        return _unavailable(
            layer,
            known_pct=known_pct if _is_finite_number(known_pct) else None,
            unknown_pct=unknown_pct if _is_finite_number(unknown_pct) else None,
            target_pct=target_pct if _is_finite_number(target_pct) else None,
            tolerance_pct=tolerance_pct if _is_finite_number(tolerance_pct) else None,
            reason_codes=("MISSING_VALUATION",),
        )
    if target_pct is None:
        return _unavailable(
            layer,
            known_pct=known_pct if _is_finite_number(known_pct) else None,
            unknown_pct=unknown_pct if _is_finite_number(unknown_pct) else None,
            tolerance_pct=tolerance_pct if _is_finite_number(tolerance_pct) else None,
            reason_codes=("MISSING_TARGET",),
        )
    invalid = _invalid_scalar_reasons(
        known_pct=known_pct,
        unknown_pct=unknown_pct,
        target_pct=target_pct,
        tolerance_pct=tolerance_pct,
    )
    if invalid:
        return _unavailable(
            layer,
            known_pct=known_pct,
            unknown_pct=unknown_pct,
            target_pct=target_pct,
            tolerance_pct=tolerance_pct,
            reason_codes=invalid,
        )

    known = _round(float(known_pct))
    unknown = _round(float(unknown_pct))
    target = _round(float(target_pct))
    tolerance = _round(float(tolerance_pct))
    assert known is not None and unknown is not None and target is not None and tolerance is not None
    minimum = _round(known)
    maximum = _round(known + unknown)
    assert minimum is not None and maximum is not None
    lower = _round(target - tolerance)
    upper = _round(target + tolerance)
    assert lower is not None and upper is not None

    reasons: list[str] = []
    if maximum > 100.0:
        reasons.append(MASS_OVERFLOW_REASON)

    if maximum < lower:
        status = LayerExposureDeterminacy.ROBUST_UNDERWEIGHT
    elif minimum > upper:
        status = LayerExposureDeterminacy.ROBUST_OVERWEIGHT
    elif minimum >= lower and maximum <= upper:
        status = LayerExposureDeterminacy.ROBUST_ON_TARGET
    else:
        status = LayerExposureDeterminacy.AMBIGUOUS

    return LayerUncertaintyAssessment(
        layer=str(layer).strip().lower(),
        known_pct=known,
        unknown_pct=unknown,
        target_pct=target,
        tolerance_pct=tolerance,
        min_pct=minimum,
        max_pct=maximum,
        lower_bound_pct=lower,
        upper_bound_pct=upper,
        status=status,
        reason_codes=tuple(reasons),
    )


def assess_economic_exposure_determinacy(
    *,
    targets: Sequence[Tuple[str, Any]],
    known_by_layer: Optional[Mapping[str, Any]] = None,
    unknown_pct: Any = 0.0,
    tolerance_pct: Any = 0.0,
    valuation_complete: bool = True,
    unpriced: bool = False,
    max_unknown_portfolio_pct: Optional[float] = None,
) -> ExposureDeterminacyView:
    """Shadow portfolio assessment. ceiling=None is diagnostic-only; never BOUNDED/UNSAFE."""
    del max_unknown_portfolio_pct  # accepted for future callers; 7F does not apply a ceiling
    known_map = {str(key).strip().lower(): value for key, value in (known_by_layer or {}).items()}
    portfolio_reasons: list[str] = []

    if not targets:
        return ExposureDeterminacyView(
            evaluation_mode=ShadowEvaluationMode.UNAVAILABLE,
            classification_complete=False,
            known_pct=None,
            unknown_pct=_round(float(unknown_pct)) if _is_finite_number(unknown_pct) else None,
            layers=(),
            reason_codes=("TARGET_NOT_CONFIGURED",),
            max_unknown_portfolio_pct=None,
        )

    if not valuation_complete or unpriced:
        portfolio_reasons.append("MISSING_VALUATION" if not valuation_complete else "UNPRICED_HOLDINGS")
        layers = tuple(
            _unavailable(
                str(layer),
                known_pct=known_map.get(str(layer).strip().lower()),
                unknown_pct=unknown_pct,
                target_pct=target,
                tolerance_pct=tolerance_pct,
                reason_codes=portfolio_reasons,
            )
            for layer, target in targets
        )
        return ExposureDeterminacyView(
            evaluation_mode=ShadowEvaluationMode.UNAVAILABLE,
            classification_complete=False,
            known_pct=None,
            unknown_pct=_round(float(unknown_pct)) if _is_finite_number(unknown_pct) else None,
            layers=layers,
            reason_codes=tuple(dict.fromkeys(portfolio_reasons)),
            max_unknown_portfolio_pct=None,
        )

    layers = tuple(
        assess_layer_uncertainty(
            layer=str(layer),
            known_pct=known_map.get(str(layer).strip().lower(), 0.0),
            unknown_pct=unknown_pct,
            target_pct=target,
            tolerance_pct=tolerance_pct,
            valuation_available=True,
        )
        for layer, target in targets
    )
    unavailable = all(row.status == LayerExposureDeterminacy.UNAVAILABLE for row in layers)
    unknown_value = _round(float(unknown_pct)) if _is_finite_number(unknown_pct) else None
    known_total = None
    if not unavailable and _is_finite_number(unknown_pct):
        known_total = _round(
            sum(float(row.known_pct or 0.0) for row in layers if row.known_pct is not None)
        )
    for row in layers:
        portfolio_reasons.extend(row.reason_codes)
    if unknown_value == 0.0 and not unavailable:
        classification_complete = True
    else:
        classification_complete = False
    return ExposureDeterminacyView(
        evaluation_mode=(
            ShadowEvaluationMode.UNAVAILABLE
            if unavailable
            else ShadowEvaluationMode.SHADOW_EVALUATED
        ),
        classification_complete=classification_complete,
        known_pct=known_total,
        unknown_pct=unknown_value,
        layers=layers,
        reason_codes=tuple(dict.fromkeys(portfolio_reasons)),
        max_unknown_portfolio_pct=None,
    )


def empty_exposure_determinacy(*, reason: str = "EXPOSURE_NOT_REQUESTED") -> ExposureDeterminacyView:
    return ExposureDeterminacyView(
        evaluation_mode=ShadowEvaluationMode.UNAVAILABLE,
        classification_complete=False,
        known_pct=None,
        unknown_pct=None,
        layers=(),
        reason_codes=(reason,),
        max_unknown_portfolio_pct=None,
    )
