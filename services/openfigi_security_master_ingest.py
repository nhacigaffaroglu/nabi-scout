"""Controlled OpenFIGI → Security Master ingest.

Persists identity + FIXED_INCOME facts only. Never writes SUKUK.
Names, fund membership, coupon, and maturity are not classification inputs.
Does not change source precedence. Does not enable hybrid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from repositories.security_master_repository import PersistFactsResult, facts_content_equal
from services.openfigi_client import (
    ID_CUSIP,
    ID_SEDOL,
    MATCH_MULTIPLE,
    OpenFigiJob,
    OpenFigiJobResult,
)
from services.openfigi_evidence_qualification import (
    OPENFIGI_FIXED_INCOME_EXACT,
    OpenFigiQualification,
    is_explicit_openfigi_sukuk,
    normalize_type,
    qualify_mapping,
)
from services.security_identifier_validation import assess_identifier
from services.security_master_contract import (
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_SEDOL,
    INSTRUMENT_FIXED_INCOME,
    INSTRUMENT_SUKUK,
    SOURCE_PRECEDENCE,
    SOURCE_PROVIDER_EXPLICIT,
    SecurityFact,
)
from services.security_master_service import SecurityMasterService
from services.sukuk_evidence_contract import classify_from_name_or_fund

OPENFIGI_SOURCE_REFERENCE = "openfigi.v3.mapping"
OPENFIGI_ID_TYPE_TO_IDENTIFIER = {
    ID_SEDOL: IDENTIFIER_TYPE_SEDOL,
    ID_CUSIP: IDENTIFIER_TYPE_CUSIP,
}

ACTION_INSERT = "INSERT"
ACTION_UPDATE = "UPDATE"
ACTION_NOOP = "NOOP"
ACTION_CONFLICT = "CONFLICT"
ACTION_SKIP = "SKIP"

WRITE_GATE_PASS = "PASS"
WRITE_GATE_FAIL = "FAIL"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity_key(identifier: Any, identifier_type: Any, source: Any) -> tuple[str, str, str]:
    return (
        str(identifier or "").strip().upper(),
        str(identifier_type or "").strip().upper(),
        str(source or "").strip(),
    )


def _fact_key(row: Mapping[str, Any] | SecurityFact) -> tuple[str, str, str]:
    if isinstance(row, SecurityFact):
        return _identity_key(row.identifier, row.identifier_type, row.source)
    return _identity_key(row.get("identifier"), row.get("identifier_type"), row.get("source"))


def whitelist_supports_fixed_income(security_type: Any, security_type2: Any) -> bool:
    """Exact 7I.1 tokens only. marketSector is inventory, not a mapper."""
    for token in (normalize_type(security_type), normalize_type(security_type2)):
        if token and token in OPENFIGI_FIXED_INCOME_EXACT:
            return True
    return False


def canonical_openfigi_instrument(qualification: OpenFigiQualification) -> str:
    """Ingest canonical type. SUKUK is never produced here."""
    _ = classify_from_name_or_fund(qualification.provider_name, None)
    if is_explicit_openfigi_sukuk(qualification.security_type, qualification.security_type2):
        return ""
    if qualification.instrument_type == INSTRUMENT_SUKUK:
        return ""
    if qualification.instrument_type != INSTRUMENT_FIXED_INCOME:
        return ""
    if qualification.safety != "safe":
        return ""
    if not whitelist_supports_fixed_income(
        qualification.security_type, qualification.security_type2
    ):
        return ""
    return INSTRUMENT_FIXED_INCOME


def jobs_from_official_holdings(holdings: Sequence[Any]) -> tuple[tuple[OpenFigiJob, str, float], ...]:
    """One validated SEDOL/CUSIP job per official holding. Cash&Other is omitted."""
    seen: set[tuple[str, str]] = set()
    rows: list[tuple[OpenFigiJob, str, float]] = []
    for holding in holdings:
        ticker = assess_identifier(getattr(holding, "ticker", None))
        cusip = assess_identifier(getattr(holding, "cusip_raw", None))
        chosen: Optional[OpenFigiJob] = None
        if ticker.usability == "VALID_SEDOL" and ticker.identifier:
            chosen = OpenFigiJob(ID_SEDOL, ticker.identifier)
        elif ticker.usability == "VALID_CUSIP" and ticker.identifier:
            chosen = OpenFigiJob(ID_CUSIP, ticker.identifier)
        elif cusip.usability == "VALID_CUSIP" and cusip.identifier:
            chosen = OpenFigiJob(ID_CUSIP, cusip.identifier)
        elif cusip.usability == "VALID_SEDOL" and cusip.identifier:
            chosen = OpenFigiJob(ID_SEDOL, cusip.identifier)
        if chosen is None:
            continue
        key = (chosen.id_type, chosen.id_value)
        if key in seen:
            continue
        seen.add(key)
        name = str(getattr(holding, "security_name", "") or "")
        weight = float(getattr(holding, "weight_pct", 0.0) or 0.0)
        rows.append((chosen, name, weight))
    return tuple(rows)


def openfigi_fact_metadata(qualification: OpenFigiQualification, *, id_type: str) -> dict[str, Any]:
    payload = {
        "figi": qualification.figi,
        "compositeFIGI": qualification.composite_figi,
        "shareClassFIGI": qualification.share_class_figi,
        "securityType": qualification.security_type,
        "securityType2": qualification.security_type2,
        "marketSector": qualification.market_sector,
        "idType": id_type,
    }
    return {key: value for key, value in payload.items() if str(value or "").strip()}


def fact_from_qualification(
    job: OpenFigiJob,
    qualification: OpenFigiQualification,
    *,
    observed_at: Optional[str] = None,
) -> Optional[SecurityFact]:
    identifier_type = OPENFIGI_ID_TYPE_TO_IDENTIFIER.get(job.id_type)
    instrument = canonical_openfigi_instrument(qualification)
    if identifier_type is None or instrument != INSTRUMENT_FIXED_INCOME:
        return None
    if not qualification.identity_resolved or not job.id_value.strip():
        return None
    return SecurityFact(
        identifier=job.id_value,
        identifier_type=identifier_type,
        instrument_type=INSTRUMENT_FIXED_INCOME,
        source=SOURCE_PROVIDER_EXPLICIT,
        observed_at=observed_at or _utcnow_iso(),
        source_reference=OPENFIGI_SOURCE_REFERENCE,
        metadata=openfigi_fact_metadata(qualification, id_type=job.id_type),
    )


@dataclass(frozen=True)
class OpenFigiIngestPlanRow:
    action: str
    identifier: str
    identifier_type: str
    reason: str
    weight_pct: float = 0.0
    instrument_type: str = ""
    fact: Optional[SecurityFact] = None
    match_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "identifier": self.identifier,
            "identifier_type": self.identifier_type,
            "reason": self.reason,
            "weight_pct": self.weight_pct,
            "instrument_type": self.instrument_type,
            "match_status": self.match_status,
        }


@dataclass
class OpenFigiIngestPlan:
    rows: list[OpenFigiIngestPlanRow] = field(default_factory=list)
    multiple_matches: int = 0
    sukuk_planned: int = 0
    write_gate: str = WRITE_GATE_FAIL
    write_gate_reasons: tuple[str, ...] = ()

    @property
    def inserts(self) -> int:
        return sum(1 for row in self.rows if row.action == ACTION_INSERT)

    @property
    def updates(self) -> int:
        return sum(1 for row in self.rows if row.action == ACTION_UPDATE)

    @property
    def noops(self) -> int:
        return sum(1 for row in self.rows if row.action == ACTION_NOOP)

    @property
    def conflicts(self) -> int:
        return sum(1 for row in self.rows if row.action == ACTION_CONFLICT)

    @property
    def skipped(self) -> int:
        return sum(1 for row in self.rows if row.action == ACTION_SKIP)

    @property
    def fixed_income_planned(self) -> int:
        return sum(
            1
            for row in self.rows
            if row.action in {ACTION_INSERT, ACTION_UPDATE}
            and row.instrument_type == INSTRUMENT_FIXED_INCOME
        )

    @property
    def writable_facts(self) -> tuple[SecurityFact, ...]:
        return tuple(
            row.fact
            for row in self.rows
            if row.action in {ACTION_INSERT, ACTION_UPDATE} and row.fact is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "inserts": self.inserts,
            "updates": self.updates,
            "noops": self.noops,
            "conflicts": self.conflicts,
            "skipped": self.skipped,
            "fixed_income_planned": self.fixed_income_planned,
            "sukuk_planned": self.sukuk_planned,
            "multiple_matches": self.multiple_matches,
            "write_gate": self.write_gate,
            "write_gate_reasons": list(self.write_gate_reasons),
        }


def _existing_index(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {_fact_key(row): dict(row) for row in rows if _fact_key(row)[0]}


def _same_identity_rows(
    existing: Mapping[tuple[str, str, str], Mapping[str, Any]],
    identifier: str,
    identifier_type: str,
) -> list[Mapping[str, Any]]:
    ident = identifier.strip().upper()
    itype = identifier_type.strip().upper()
    return [
        row
        for key, row in existing.items()
        if key[0] == ident and key[1] == itype
    ]


def _higher_precedence_conflict(
    existing_rows: Sequence[Mapping[str, Any]],
    instrument_type: str,
) -> Optional[str]:
    openfigi_rank = SOURCE_PRECEDENCE.get(SOURCE_PROVIDER_EXPLICIT, 20)
    for row in existing_rows:
        source = str(row.get("source") or "")
        rank = SOURCE_PRECEDENCE.get(source, 1000)
        if rank >= openfigi_rank:
            continue
        other = str(row.get("instrument_type") or "").strip().upper()
        if other and other != instrument_type:
            return "HIGHER_PRECEDENCE_CONFLICT"
    return None


def _same_rank_conflict(
    existing_rows: Sequence[Mapping[str, Any]],
    instrument_type: str,
) -> Optional[str]:
    openfigi_rank = SOURCE_PRECEDENCE.get(SOURCE_PROVIDER_EXPLICIT, 20)
    for row in existing_rows:
        source = str(row.get("source") or "")
        if SOURCE_PRECEDENCE.get(source, 1000) != openfigi_rank:
            continue
        if source == SOURCE_PROVIDER_EXPLICIT:
            continue
        other = str(row.get("instrument_type") or "").strip().upper()
        if other and other != instrument_type:
            return "SAME_RANK_CONFLICT"
    return None


def evaluate_write_gate(plan: OpenFigiIngestPlan) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    if plan.sukuk_planned:
        reasons.append("SUKUK_WRITES_FORBIDDEN")
    if plan.multiple_matches:
        reasons.append("MULTIPLE_MATCHES")
    if plan.conflicts:
        reasons.append("CONFLICTS")
    writable = [row for row in plan.rows if row.action in {ACTION_INSERT, ACTION_UPDATE}]
    if any(row.instrument_type != INSTRUMENT_FIXED_INCOME for row in writable):
        reasons.append("NON_FIXED_INCOME_WRITE")
    if any(row.fact is None or row.fact.instrument_type == INSTRUMENT_SUKUK for row in writable):
        reasons.append("SUKUK_OR_MISSING_FACT")
    for row in writable:
        fact = row.fact
        if fact is None:
            continue
        meta = fact.metadata or {}
        if not whitelist_supports_fixed_income(meta.get("securityType"), meta.get("securityType2")):
            reasons.append("WHITELIST_UNSUPPORTED")
            break
    if reasons:
        return WRITE_GATE_FAIL, tuple(dict.fromkeys(reasons))
    return WRITE_GATE_PASS, ()


def plan_openfigi_ingest(
    mappings: Sequence[tuple[OpenFigiJob, OpenFigiJobResult, float]],
    *,
    existing_rows: Sequence[Mapping[str, Any]] = (),
    official_names: Optional[Mapping[tuple[str, str], str]] = None,
    observed_at: Optional[str] = None,
) -> OpenFigiIngestPlan:
    """Plan mutations. Does not write."""
    names = official_names or {}
    existing = _existing_index(existing_rows)
    stamp = observed_at or _utcnow_iso()
    plan = OpenFigiIngestPlan()
    for job, result, weight in mappings:
        identifier_type = OPENFIGI_ID_TYPE_TO_IDENTIFIER.get(job.id_type, "")
        official_name = names.get((job.id_type, job.id_value), "")
        qualification = qualify_mapping(result, official_name=official_name)
        if result.match_status == MATCH_MULTIPLE or qualification.match_status == MATCH_MULTIPLE:
            plan.multiple_matches += 1
            plan.rows.append(
                OpenFigiIngestPlanRow(
                    action=ACTION_SKIP,
                    identifier=job.id_value,
                    identifier_type=identifier_type,
                    reason="MULTIPLE_MATCHES",
                    weight_pct=weight,
                    match_status=qualification.match_status,
                )
            )
            continue
        if is_explicit_openfigi_sukuk(qualification.security_type, qualification.security_type2):
            plan.sukuk_planned += 1
            plan.rows.append(
                OpenFigiIngestPlanRow(
                    action=ACTION_SKIP,
                    identifier=job.id_value,
                    identifier_type=identifier_type,
                    reason="SUKUK_HARD_GUARD",
                    weight_pct=weight,
                    instrument_type=INSTRUMENT_SUKUK,
                    match_status=qualification.match_status,
                )
            )
            continue
        fact = fact_from_qualification(job, qualification, observed_at=stamp)
        if fact is None:
            plan.rows.append(
                OpenFigiIngestPlanRow(
                    action=ACTION_SKIP,
                    identifier=job.id_value,
                    identifier_type=identifier_type,
                    reason=qualification.reason or "NOT_QUALIFIED_FIXED_INCOME",
                    weight_pct=weight,
                    match_status=qualification.match_status,
                )
            )
            continue
        peers = _same_identity_rows(existing, fact.identifier, fact.identifier_type)
        higher = _higher_precedence_conflict(peers, fact.instrument_type)
        if higher:
            plan.rows.append(
                OpenFigiIngestPlanRow(
                    action=ACTION_CONFLICT,
                    identifier=fact.identifier,
                    identifier_type=fact.identifier_type,
                    reason=higher,
                    weight_pct=weight,
                    instrument_type=fact.instrument_type,
                    fact=fact,
                    match_status=qualification.match_status,
                )
            )
            continue
        same_rank = _same_rank_conflict(peers, fact.instrument_type)
        if same_rank:
            plan.rows.append(
                OpenFigiIngestPlanRow(
                    action=ACTION_CONFLICT,
                    identifier=fact.identifier,
                    identifier_type=fact.identifier_type,
                    reason=same_rank,
                    weight_pct=weight,
                    instrument_type=fact.instrument_type,
                    fact=fact,
                    match_status=qualification.match_status,
                )
            )
            continue
        key = _fact_key(fact)
        current = existing.get(key)
        if current is None:
            plan.rows.append(
                OpenFigiIngestPlanRow(
                    action=ACTION_INSERT,
                    identifier=fact.identifier,
                    identifier_type=fact.identifier_type,
                    reason="NEW_OPENFIGI_FIXED_INCOME",
                    weight_pct=weight,
                    instrument_type=INSTRUMENT_FIXED_INCOME,
                    fact=fact,
                    match_status=qualification.match_status,
                )
            )
            continue
        current_type = str(current.get("instrument_type") or "").strip().upper()
        if current_type and current_type != INSTRUMENT_FIXED_INCOME:
            plan.rows.append(
                OpenFigiIngestPlanRow(
                    action=ACTION_CONFLICT,
                    identifier=fact.identifier,
                    identifier_type=fact.identifier_type,
                    reason="SAME_SOURCE_TYPE_CONFLICT",
                    weight_pct=weight,
                    instrument_type=fact.instrument_type,
                    fact=fact,
                    match_status=qualification.match_status,
                )
            )
            continue
        payload = {
            "identifier": fact.identifier,
            "identifier_type": fact.identifier_type,
            "instrument_type": fact.instrument_type,
            "source": fact.source,
            "symbol": fact.symbol,
            "exchange": fact.exchange,
            "issuer_name": fact.issuer_name,
            "source_reference": fact.source_reference,
            "metadata": dict(fact.metadata or {}),
        }
        if facts_content_equal(current, payload):
            plan.rows.append(
                OpenFigiIngestPlanRow(
                    action=ACTION_NOOP,
                    identifier=fact.identifier,
                    identifier_type=fact.identifier_type,
                    reason="IDEMPOTENT",
                    weight_pct=weight,
                    instrument_type=INSTRUMENT_FIXED_INCOME,
                    fact=fact,
                    match_status=qualification.match_status,
                )
            )
            continue
        plan.rows.append(
            OpenFigiIngestPlanRow(
                action=ACTION_UPDATE,
                identifier=fact.identifier,
                identifier_type=fact.identifier_type,
                reason="OPENFIGI_FACT_CHANGED",
                weight_pct=weight,
                instrument_type=INSTRUMENT_FIXED_INCOME,
                fact=fact,
                match_status=qualification.match_status,
            )
        )
    gate, reasons = evaluate_write_gate(plan)
    plan.write_gate = gate
    plan.write_gate_reasons = reasons
    return plan


def ingest_openfigi_facts(
    service: SecurityMasterService,
    plan: OpenFigiIngestPlan,
) -> PersistFactsResult:
    """Write planned FIXED_INCOME facts only. Fail closed if the gate failed."""
    if plan.write_gate != WRITE_GATE_PASS:
        return PersistFactsResult(inserted=0, updated=0, unchanged=0, rows=[])
    facts = plan.writable_facts
    if any(fact.instrument_type == INSTRUMENT_SUKUK for fact in facts):
        return PersistFactsResult(inserted=0, updated=0, unchanged=0, rows=[])
    if not facts:
        return PersistFactsResult(inserted=0, updated=0, unchanged=0, rows=[])
    return service.repo.persist_facts(facts)
