"""Resolve identifier aliases and economic layers. No name joins.

Loads from Security Master rows whose source is identifier_alias or
economic_classification. instrument_type on those rows is UNKNOWN and
is not used as economic evidence.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from services.security_identifier_validation import assess_identifier
from services.security_identity_contract import (
    ECONOMIC_LAYERS,
    ECONOMIC_SOURCE_PRECEDENCE,
    IDENTIFIER_TYPE_FIGI,
    SOURCE_ECONOMIC_CLASSIFICATION,
    SOURCE_IDENTIFIER_ALIAS,
    EconomicClassification,
    EconomicResolution,
    IdentifierAlias,
)
from services.security_master_contract import (
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_UNKNOWN,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNKNOWN,
    SOURCE_PROVIDER_EXPLICIT,
    SecurityFact,
)
from services.security_master_service import (
    SecurityMasterService,
    infer_identifier_type,
    normalize_identifier,
)
from services.universe_listing_identity import listing_identity


def _norm_id(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def _tokens_from_raw(raw: Any) -> tuple[tuple[str, str], ...]:
    text = str(raw or "").strip()
    if not text:
        return ()
    tokens: list[tuple[str, str]] = []
    ticker = listing_identity(text)
    if ticker:
        tokens.append((ticker, IDENTIFIER_TYPE_TICKER))
    compact = _norm_id(text)
    assessed = assess_identifier(text)
    if assessed.identifier and assessed.identifier_type:
        tokens.append((assessed.identifier, assessed.identifier_type))
    inferred = infer_identifier_type(compact)
    if compact and inferred != IDENTIFIER_TYPE_TICKER:
        tokens.append((compact, inferred))
    if compact.startswith("BBG") and len(compact) >= 12:
        tokens.append((compact, IDENTIFIER_TYPE_FIGI))
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for item in tokens:
        if item in seen or not item[0]:
            continue
        seen.add(item)
        unique.append(item)
    return tuple(unique)


class SecurityIdentityService:
    def __init__(
        self,
        *,
        aliases: Sequence[IdentifierAlias] = (),
        classifications: Sequence[EconomicClassification] = (),
    ) -> None:
        self._aliases = list(aliases)
        self._classifications = list(classifications)
        self._alias_index: dict[tuple[str, str], set[str]] = {}
        self._figi_index: dict[str, set[str]] = {}
        self._by_canonical: dict[str, list[EconomicClassification]] = {}
        self._rebuild()

    def _rebuild(self) -> None:
        self._alias_index = {}
        self._figi_index = {}
        self._by_canonical = {}
        for alias in self._aliases:
            ident = str(alias.identifier or "").strip().upper()
            itype = str(alias.identifier_type or "").strip().upper()
            canonical = str(alias.canonical_id or "").strip()
            if not ident or not itype or not canonical:
                continue
            self._alias_index.setdefault((ident, itype), set()).add(canonical)
            figi = str((alias.metadata or {}).get("figi") or "").strip().upper()
            if figi:
                self._figi_index.setdefault(figi, set()).add(canonical)
        for row in self._classifications:
            canonical = str(row.canonical_id or "").strip()
            if not canonical:
                continue
            self._by_canonical.setdefault(canonical, []).append(row)

    def register_alias(self, alias: IdentifierAlias) -> None:
        self._aliases.append(alias)
        self._rebuild()

    def register_classification(self, row: EconomicClassification) -> None:
        self._classifications.append(row)
        self._rebuild()

    @property
    def aliases(self) -> tuple[IdentifierAlias, ...]:
        return tuple(self._aliases)

    @property
    def classifications(self) -> tuple[EconomicClassification, ...]:
        return tuple(self._classifications)

    def resolve_canonical_ids(self, raw: Any) -> tuple[str, ...]:
        found: set[str] = set()
        for ident, itype in _tokens_from_raw(raw):
            if itype == IDENTIFIER_TYPE_FIGI:
                found.update(self._figi_index.get(ident, set()))
                found.update(self._alias_index.get((ident, IDENTIFIER_TYPE_FIGI), set()))
                continue
            found.update(self._alias_index.get((ident, itype), set()))
        return tuple(sorted(found))

    def resolve_economic_layer(self, raws: Sequence[Any]) -> EconomicResolution:
        canonicals: set[str] = set()
        for raw in raws:
            canonicals.update(self.resolve_canonical_ids(raw))
        if not canonicals:
            return EconomicResolution(None, None, RESOLUTION_UNKNOWN, limitation="NO_ALIAS")
        if len(canonicals) > 1:
            return EconomicResolution(
                None,
                None,
                RESOLUTION_CONFLICT,
                limitation="AMBIGUOUS_ALIAS",
            )
        canonical = next(iter(canonicals))
        rows = list(self._by_canonical.get(canonical, ()))
        if not rows:
            return EconomicResolution(
                canonical,
                None,
                RESOLUTION_UNKNOWN,
                limitation="NO_ECONOMIC_CLASSIFICATION",
            )
        ranked = sorted(
            rows,
            key=lambda item: (
                ECONOMIC_SOURCE_PRECEDENCE.get(item.source, 1000),
                item.source,
                item.observed_at,
            ),
        )
        best = ECONOMIC_SOURCE_PRECEDENCE.get(ranked[0].source, 1000)
        top = [item for item in ranked if ECONOMIC_SOURCE_PRECEDENCE.get(item.source, 1000) == best]
        layers = {item.economic_layer for item in top if item.economic_layer in ECONOMIC_LAYERS}
        if len(layers) != 1:
            return EconomicResolution(
                canonical,
                None,
                RESOLUTION_CONFLICT,
                limitation="ECONOMIC_SOURCE_CONFLICT",
            )
        chosen = top[0]
        return EconomicResolution(
            canonical,
            next(iter(layers)),
            RESOLUTION_RESOLVED,
            source=chosen.source,
        )


def identity_service_from_security_master(
    master: SecurityMasterService,
) -> SecurityIdentityService:
    aliases: list[IdentifierAlias] = []
    classifications: list[EconomicClassification] = []
    for raw in master.repo.list_all():
        source = str(raw.get("source") or "").strip()
        if source not in {SOURCE_IDENTIFIER_ALIAS, SOURCE_ECONOMIC_CLASSIFICATION}:
            continue
        meta = dict(raw.get("metadata") or {})
        canonical = str(meta.get("canonical_id") or "").strip()
        if not canonical:
            continue
        observed = str(raw.get("observed_at") or "")
        aliases.append(
            IdentifierAlias(
                identifier=str(raw.get("identifier") or ""),
                identifier_type=str(raw.get("identifier_type") or ""),
                canonical_id=canonical,
                source=source,
                observed_at=observed,
                metadata=meta,
            )
        )
        layer = str(meta.get("economic_layer") or "").strip().lower()
        if source == SOURCE_ECONOMIC_CLASSIFICATION and layer in ECONOMIC_LAYERS:
            classifications.append(
                EconomicClassification(
                    canonical_id=canonical,
                    economic_layer=layer,
                    source=str(meta.get("economic_source") or SOURCE_PROVIDER_EXPLICIT),
                    evidence_type=str(meta.get("evidence_type") or ""),
                    evidence_reference=str(meta.get("evidence_reference") or ""),
                    status=RESOLUTION_RESOLVED,
                    observed_at=observed,
                    metadata=meta,
                )
            )
    return SecurityIdentityService(aliases=aliases, classifications=classifications)


def try_identity_service_from_wealth(wealth: Any) -> Optional[SecurityIdentityService]:
    client = getattr(wealth, "client", None) if wealth is not None else None
    if client is None:
        return None
    from services.security_master_service import production_security_master

    return identity_service_from_security_master(production_security_master(client))


def alias_fact(
    *,
    identifier: str,
    identifier_type: str,
    canonical_id: str,
    observed_at: str,
    metadata: Optional[Mapping[str, Any]] = None,
) -> SecurityFact:
    ident, itype = normalize_identifier(identifier, identifier_type=identifier_type)
    if itype == IDENTIFIER_TYPE_FIGI:
        raise ValueError("FIGI is stored as alias metadata, not security_master identifier_type")
    payload = dict(metadata or {})
    payload["canonical_id"] = canonical_id
    payload.setdefault("role", "alias")
    return SecurityFact(
        identifier=ident,
        identifier_type=itype,
        instrument_type=INSTRUMENT_UNKNOWN,
        source=SOURCE_IDENTIFIER_ALIAS,
        observed_at=observed_at,
        symbol=ident if itype == IDENTIFIER_TYPE_TICKER else None,
        metadata=payload,
    )


def economic_fact(
    *,
    identifier: str,
    identifier_type: str,
    classification: EconomicClassification,
) -> SecurityFact:
    ident, itype = normalize_identifier(identifier, identifier_type=identifier_type)
    if itype == IDENTIFIER_TYPE_FIGI:
        raise ValueError("FIGI is stored as alias metadata, not security_master identifier_type")
    meta = dict(classification.metadata or {})
    meta.update(
        {
            "canonical_id": classification.canonical_id,
            "economic_layer": classification.economic_layer,
            "economic_source": classification.source,
            "evidence_type": classification.evidence_type,
            "evidence_reference": classification.evidence_reference,
            "role": "economic",
        }
    )
    figi = classification.canonical_id.removeprefix("FIGI:")
    if figi:
        meta.setdefault("figi", figi)
    return SecurityFact(
        identifier=ident,
        identifier_type=itype,
        instrument_type=INSTRUMENT_UNKNOWN,
        source=SOURCE_ECONOMIC_CLASSIFICATION,
        observed_at=classification.observed_at,
        symbol=ident if itype == IDENTIFIER_TYPE_TICKER else None,
        source_reference=classification.evidence_reference,
        metadata=meta,
    )
