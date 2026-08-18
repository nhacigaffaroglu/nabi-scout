from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from repositories.portfolio_allocation_policy_repository import (
    PortfolioAllocationPolicyRepository,
)
from services.portfolio_allocation_intelligence import (
    ALLOCATION_DRIFT_TOLERANCE_PCT,
    AllocationDimension,
    AllocationPolicy,
    AllocationProvenance,
    AllocationTarget,
    policy_is_configured,
)
from services.wealth_contract import WealthValidationError

PERSISTED_PAYLOAD_KEYS = frozenset(
    {
        "dimension",
        "targets",
        "tolerance_pct",
        "provenance",
    }
)
FORBIDDEN_DERIVED_KEYS = frozenset(
    {
        "observable_weight_pct",
        "drift",
        "drift_pct",
        "routing",
        "before_drift_score",
        "after_drift_score",
        "improvement",
        "market_value",
        "current_weights",
    }
)


class AllocationPolicyStoreError(RuntimeError):
    """Persisted target settings cannot be read or written."""


def policy_record_payload(policy: AllocationPolicy) -> Dict[str, Any]:
    if not policy_is_configured(policy):
        raise WealthValidationError("Kaydedilecek hedef dağılım yok.")
    policy.validate()
    dimensions = {target.dimension for target in policy.targets}
    if len(dimensions) != 1:
        raise WealthValidationError("Kayıtlı hedef tek boyutta olmalıdır.")
    dimension = next(iter(dimensions))
    payload = {
        "dimension": dimension.value,
        "targets": [_target_to_dict(target) for target in policy.targets],
        "tolerance_pct": float(policy.tolerance_pct),
        "provenance": policy.provenance.value,
    }
    extra = set(payload) - PERSISTED_PAYLOAD_KEYS
    overlap = set(payload) & FORBIDDEN_DERIVED_KEYS
    if extra or overlap:
        raise WealthValidationError("Türetilmiş dağılım alanları kaydedilemez.")
    return payload


def policy_from_record(row: Mapping[str, Any]) -> AllocationPolicy:
    targets = tuple(_target_from_dict(item) for item in (row.get("targets") or ()))
    provenance_raw = str(row.get("provenance") or AllocationProvenance.USER_DEFINED.value)
    try:
        provenance = AllocationProvenance(provenance_raw)
    except ValueError as exc:
        raise WealthValidationError("Geçersiz hedef kaynak bilgisi.") from exc
    tolerance = row.get("tolerance_pct", ALLOCATION_DRIFT_TOLERANCE_PCT)
    policy = AllocationPolicy(
        targets=targets,
        tolerance_pct=float(tolerance),
        provenance=provenance,
    )
    policy.validate()
    if not policy_is_configured(policy):
        raise WealthValidationError("Kayıtlı hedef dağılım geçersiz.")
    return policy


def _target_to_dict(target: AllocationTarget) -> Dict[str, Any]:
    return {
        "bucket_id": str(target.bucket_id).strip().lower(),
        "dimension": target.dimension.value,
        "target_weight_pct": float(target.target_weight_pct),
        "min_weight_pct": None if target.min_weight_pct is None else float(target.min_weight_pct),
        "max_weight_pct": None if target.max_weight_pct is None else float(target.max_weight_pct),
        "source": target.source.value,
    }


def _target_from_dict(raw: Any) -> AllocationTarget:
    if not isinstance(raw, Mapping):
        raise WealthValidationError("Geçersiz hedef kova kaydı.")
    try:
        dimension = AllocationDimension(str(raw.get("dimension") or ""))
        source = AllocationProvenance(str(raw.get("source") or AllocationProvenance.USER_DEFINED.value))
    except ValueError as exc:
        raise WealthValidationError("Geçersiz hedef kova kaydı.") from exc
    return AllocationTarget(
        bucket_id=str(raw.get("bucket_id") or ""),
        dimension=dimension,
        target_weight_pct=float(raw.get("target_weight_pct") or 0.0),
        min_weight_pct=None if raw.get("min_weight_pct") is None else float(raw["min_weight_pct"]),
        max_weight_pct=None if raw.get("max_weight_pct") is None else float(raw["max_weight_pct"]),
        source=source,
    )


class PortfolioAllocationPolicyService:
    def __init__(self, client, user_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.repo = PortfolioAllocationPolicyRepository(client)

    def get_policy(self, portfolio_id: str) -> Optional[AllocationPolicy]:
        try:
            row = self.repo.get_for_portfolio(self.user_id, str(portfolio_id))
        except Exception as exc:
            raise AllocationPolicyStoreError("Hedef ayarları şu an kullanılamıyor.") from exc
        if row is None:
            return None
        try:
            return policy_from_record(row)
        except WealthValidationError as exc:
            raise AllocationPolicyStoreError("Kayıtlı hedef dağılım okunamadı.") from exc

    def save_policy(self, portfolio_id: str, policy: AllocationPolicy) -> AllocationPolicy:
        payload = policy_record_payload(policy)
        try:
            row = self.repo.upsert(self.user_id, str(portfolio_id), payload)
        except WealthValidationError:
            raise
        except Exception as exc:
            raise AllocationPolicyStoreError("Hedef dağılım kaydedilemedi.") from exc
        return policy_from_record(row)

    def delete_policy(self, portfolio_id: str) -> None:
        try:
            self.repo.delete_for_portfolio(self.user_id, str(portfolio_id))
        except Exception as exc:
            raise AllocationPolicyStoreError("Hedef sıfırlanamadı.") from exc
