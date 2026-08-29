"""Guarded hybrid New Money policy. Default OFF. No layer-bound math.

Ceiling and robust statuses come from the 7F/7G helpers. This module only
selects STRICT / COMPLETE / BOUNDED / UNSAFE / UNAVAILABLE and the
actionable layer set. Missing flag is OFF.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple

from services.exposure_determinacy_diagnostics import (
    SHADOW_BLOCKER_NO_FILL,
    SHADOW_BLOCKER_NO_UW,
    SHADOW_BLOCKER_UNSAFE,
    ceiling_allows_bound_evaluation,
)
from services.layer_exposure_determinacy import (
    WEIGHT_QUANT,
    ExposureDeterminacyView,
    LayerExposureDeterminacy,
    ShadowEvaluationMode,
)

HYBRID_MAX_UNKNOWN_PORTFOLIO_PCT = 1.00
HYBRID_MAX_UNKNOWN_ABSOLUTE_VALUE = None
HYBRID_BOUNDED_MIX_MAINTENANCE = False

PORTFOLIO_EXPOSURE_UNAVAILABLE = "PORTFOLIO_EXPOSURE_UNAVAILABLE"
PORTFOLIO_EXPOSURE_UNSAFE = SHADOW_BLOCKER_UNSAFE
NO_ROBUST_UNDERWEIGHT_LAYER = SHADOW_BLOCKER_NO_UW
NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER = SHADOW_BLOCKER_NO_FILL

HYBRID_LIVE_BLOCKER_PRECEDENCE = (
    PORTFOLIO_EXPOSURE_UNAVAILABLE,
    PORTFOLIO_EXPOSURE_UNSAFE,
    NO_ROBUST_UNDERWEIGHT_LAYER,
    NO_ELIGIBLE_FILL_FOR_ROBUST_UNDERWEIGHT_LAYER,
)

_TRUTHY = {"1", "true", "yes", "on"}


class HybridPortfolioMode(str, Enum):
    STRICT = "STRICT"
    COMPLETE = "COMPLETE"
    BOUNDED = "BOUNDED"
    UNSAFE = "UNSAFE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class HybridExposureAllocationPolicy:
    enable_hybrid_exposure_allocation: bool = False
    max_unknown_portfolio_pct: float = HYBRID_MAX_UNKNOWN_PORTFOLIO_PCT
    max_unknown_absolute_value: Optional[float] = HYBRID_MAX_UNKNOWN_ABSOLUTE_VALUE
    bounded_mix_maintenance: bool = HYBRID_BOUNDED_MIX_MAINTENANCE

    @property
    def enabled(self) -> bool:
        return bool(self.enable_hybrid_exposure_allocation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_unknown_portfolio_pct": self.max_unknown_portfolio_pct,
            "absolute_guard": (
                None
                if self.max_unknown_absolute_value is None
                else self.max_unknown_absolute_value
            ),
            "bounded_mix_maintenance": self.bounded_mix_maintenance,
        }


@dataclass(frozen=True)
class HybridLayerRef:
    bucket_id: str
    drift_pct: float


@dataclass(frozen=True)
class HybridAllocationIntent:
    policy: HybridExposureAllocationPolicy
    mode: HybridPortfolioMode
    blocker: Optional[str] = None
    underweight_rows: Tuple[HybridLayerRef, ...] = ()
    overweight_layers: Tuple[str, ...] = ()
    allow_mix_maintenance: bool = True
    use_robust_layers: bool = False


def resolve_hybrid_allocation_policy(
    enable_hybrid_exposure_allocation: Optional[bool] = None,
    *,
    policy: Optional[HybridExposureAllocationPolicy] = None,
) -> HybridExposureAllocationPolicy:
    """Missing / None / False → OFF. Never infer ON from absent config."""
    if policy is not None:
        return policy
    if enable_hybrid_exposure_allocation is True:
        return HybridExposureAllocationPolicy(enable_hybrid_exposure_allocation=True)
    return HybridExposureAllocationPolicy(enable_hybrid_exposure_allocation=False)


def explicit_flag_is_enabled(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in _TRUTHY


def _round_unknown(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, WEIGHT_QUANT)


def resolve_hybrid_portfolio_mode(
    *,
    policy: HybridExposureAllocationPolicy,
    determinacy: Optional[ExposureDeterminacyView],
    valuation_complete: bool = True,
    unpriced: bool = False,
    dimension: Optional[str] = None,
) -> HybridPortfolioMode:
    if not policy.enabled:
        return HybridPortfolioMode.STRICT
    dimension_value = getattr(dimension, "value", dimension)
    if dimension_value not in {None, "ECONOMIC_EXPOSURE"}:
        return HybridPortfolioMode.STRICT
    if determinacy is None:
        return HybridPortfolioMode.UNAVAILABLE
    if determinacy.evaluation_mode == ShadowEvaluationMode.UNAVAILABLE:
        return HybridPortfolioMode.UNAVAILABLE
    if not valuation_complete or unpriced:
        return HybridPortfolioMode.UNAVAILABLE
    unknown = _round_unknown(determinacy.unknown_pct)
    if unknown is None:
        return HybridPortfolioMode.UNAVAILABLE
    if unknown == 0.0:
        return HybridPortfolioMode.COMPLETE
    if ceiling_allows_bound_evaluation(unknown, policy.max_unknown_portfolio_pct) is False:
        return HybridPortfolioMode.UNSAFE
    return HybridPortfolioMode.BOUNDED


def select_hybrid_allocation_intent(
    *,
    policy: HybridExposureAllocationPolicy,
    determinacy: Optional[ExposureDeterminacyView],
    valuation_complete: bool = True,
    unpriced: bool = False,
    dimension: Optional[str] = None,
) -> HybridAllocationIntent:
    """Single New Money policy fork. Callers must not re-derive U or bounds."""
    mode = resolve_hybrid_portfolio_mode(
        policy=policy,
        determinacy=determinacy,
        valuation_complete=valuation_complete,
        unpriced=unpriced,
        dimension=dimension,
    )
    if mode == HybridPortfolioMode.STRICT:
        return HybridAllocationIntent(
            policy=policy,
            mode=mode,
            allow_mix_maintenance=True,
            use_robust_layers=False,
        )
    if mode == HybridPortfolioMode.UNAVAILABLE:
        return HybridAllocationIntent(
            policy=policy,
            mode=mode,
            blocker=PORTFOLIO_EXPOSURE_UNAVAILABLE,
            allow_mix_maintenance=False,
            use_robust_layers=False,
        )
    if mode == HybridPortfolioMode.UNSAFE:
        return HybridAllocationIntent(
            policy=policy,
            mode=mode,
            blocker=PORTFOLIO_EXPOSURE_UNSAFE,
            allow_mix_maintenance=False,
            use_robust_layers=False,
        )
    if mode == HybridPortfolioMode.COMPLETE:
        return HybridAllocationIntent(
            policy=policy,
            mode=mode,
            allow_mix_maintenance=True,
            use_robust_layers=False,
        )

    layers = determinacy.layers if determinacy is not None else ()
    underweight = tuple(
        HybridLayerRef(
            bucket_id=row.layer,
            drift_pct=float(row.known_pct or 0.0) - float(row.target_pct or 0.0),
        )
        for row in layers
        if row.status == LayerExposureDeterminacy.ROBUST_UNDERWEIGHT
    )
    overweight = tuple(
        row.layer
        for row in layers
        if row.status == LayerExposureDeterminacy.ROBUST_OVERWEIGHT
    )
    return HybridAllocationIntent(
        policy=policy,
        mode=mode,
        underweight_rows=tuple(
            sorted(underweight, key=lambda row: (row.drift_pct, row.bucket_id))
        ),
        overweight_layers=overweight,
        allow_mix_maintenance=False,
        use_robust_layers=True,
    )


def first_live_blocker(limitations: Sequence[str]) -> Optional[str]:
    codes = [str(item) for item in limitations]
    for prefix in (
        *HYBRID_LIVE_BLOCKER_PRECEDENCE,
        "EXPOSURE_CLASSIFICATION_INCOMPLETE",
        "PARTICIPATION_BLOCKED",
        "CONCENTRATION_BLOCKED",
        "TRANSACTION_EFFICIENCY_BLOCKED",
        "TARGET_NOT_CONFIGURED",
    ):
        for item in codes:
            if item == prefix or item.startswith(f"{prefix}:"):
                return item
    return codes[0] if codes else None


def bounded_layer_is_actionable(status: Any) -> bool:
    value = getattr(status, "value", status)
    return value == LayerExposureDeterminacy.ROBUST_UNDERWEIGHT.value


def hybrid_policy_payload(policy: HybridExposureAllocationPolicy) -> dict[str, Any]:
    return policy.to_dict()


def overlay_adviser_hybrid_fields(
    payload: Mapping[str, Any],
    *,
    policy: HybridExposureAllocationPolicy,
    mode: HybridPortfolioMode,
    live_blocker: Optional[str],
) -> dict[str, Any]:
    out = dict(payload)
    out["hybrid_allocation_active"] = bool(policy.enabled)
    out["hybrid_policy"] = policy.to_dict()
    out["portfolio_mode"] = mode.value
    out["live_blocker"] = live_blocker
    new_money = dict(out.get("new_money") or {})
    new_money["live_blocker"] = live_blocker
    if not policy.enabled:
        new_money.setdefault("production_blocker", live_blocker)
    out["new_money"] = new_money
    return out
