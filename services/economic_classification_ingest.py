"""Plan and persist economic classification + identifier aliases.

Does not write instrument_type REIT or SUKUK. Does not change Participation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from repositories.security_master_repository import PersistFactsResult, facts_content_equal
from services.official_fund_holdings_client import OfficialHolding
from services.reit_evidence_contract import (
    is_explicit_structured_reit,
    may_persist_reit_economic,
    name_is_not_evidence,
    persist_economic_blocked_reason,
    spre_membership_is_not_evidence,
)
from services.security_identifier_validation import assess_identifier
from services.security_identity_contract import (
    EVIDENCE_OPENFIGI_MAPPING,
    EVIDENCE_OPENFIGI_SECURITY_TYPE,
    SOURCE_ECONOMIC_CLASSIFICATION,
    SOURCE_IDENTIFIER_ALIAS,
    SOURCE_PROVIDER_EXPLICIT,
    EconomicClassification,
    canonical_id_from_figi,
)
from services.security_identity_service import alias_fact, economic_fact
from services.security_master_contract import (
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    RESOLUTION_RESOLVED,
    SecurityFact,
)
from services.security_master_service import SecurityMasterService
from services.sukuk_evidence_contract import classify_from_name_or_fund
from services.universe_listing_identity import listing_identity

ACTION_INSERT = "INSERT"
ACTION_NOOP = "NOOP"
ACTION_SKIP = "SKIP"

WRITE_GATE_PASS = "PASS"
WRITE_GATE_FAIL = "FAIL"

# 7J.2 OpenFIGI EXACT_SINGLE REIT observations. Not inferred from names.
SPRE_OPENFIGI_REIT_OBSERVATIONS = (
    {
        "ticker": "IGBREIT MK",
        "sedol": "B89JCF2",
        "figi": "BBG0038P24J8",
        "security_type": "REIT",
        "security_type2": "REIT",
        "weight_pct": 4.01,
        "observed_at": "2026-08-29T00:00:00+00:00",
    },
    {
        "ticker": "CAREIT SP",
        "sedol": "BSDZ375",
        "figi": "BBG01X6Z5CK8",
        "security_type": "REIT",
        "security_type2": "REIT",
        "weight_pct": 3.18,
        "observed_at": "2026-08-29T00:00:00+00:00",
    },
    {
        "ticker": "AXREIT MK",
        "sedol": "B0CMCL8",
        "figi": "BBG000H96MN1",
        "security_type": "REIT",
        "security_type2": "REIT",
        "weight_pct": 3.10,
        "observed_at": "2026-08-29T00:00:00+00:00",
    },
    {
        "ticker": "RCR PM",
        "sedol": "BLFMKR4",
        "figi": "BBG01134SLQ9",
        "security_type": "REIT",
        "security_type2": "REIT",
        "weight_pct": 2.42,
        "observed_at": "2026-08-29T00:00:00+00:00",
    },
    {
        "ticker": "IMPACT TB",
        "sedol": "BRCFFZ1",
        "figi": "BBG005BLJ507",
        "security_type": "REIT",
        "security_type2": "REIT",
        "weight_pct": 0.91,
        "observed_at": "2026-08-29T00:00:00+00:00",
    },
    {
        "ticker": "CREIT PM",
        "sedol": "BM8GQ50",
        "figi": "BBG014MCHXJ8",
        "security_type": "REIT",
        "security_type2": "REIT",
        "weight_pct": 0.44,
        "observed_at": "2026-08-29T00:00:00+00:00",
    },
)


@dataclass(frozen=True)
class EconomicIngestPlanRow:
    action: str
    ticker: str
    sedol: str
    figi: str
    instrument_type: str
    economic_layer: str
    source: str
    evidence: str
    weight_pct: float
    reason: str
    facts: tuple[SecurityFact, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "ticker": self.ticker,
            "sedol": self.sedol,
            "figi": self.figi,
            "instrument_type": self.instrument_type,
            "economic_layer": self.economic_layer,
            "source": self.source,
            "evidence": self.evidence,
            "weight_pct": self.weight_pct,
            "reason": self.reason,
        }


@dataclass
class EconomicIngestPlan:
    rows: list[EconomicIngestPlanRow] = field(default_factory=list)
    write_gate: str = WRITE_GATE_FAIL
    write_gate_reasons: tuple[str, ...] = ()
    exact: int = 0
    ambiguous: int = 0
    unmapped: int = 0

    @property
    def facts(self) -> tuple[SecurityFact, ...]:
        planned: list[SecurityFact] = []
        for row in self.rows:
            if row.action != ACTION_SKIP:
                planned.extend(row.facts)
        return tuple(planned)


def _official_by_ticker(holdings: Sequence[OfficialHolding]) -> dict[str, OfficialHolding]:
    index: dict[str, OfficialHolding] = {}
    for holding in holdings:
        key = listing_identity(holding.ticker)
        if key:
            index[key] = holding
    return index


def plan_spre_reit_economic_ingest(
    official_holdings: Sequence[OfficialHolding],
    *,
    existing_rows: Sequence[Mapping[str, Any]] | None = None,
    observations: Sequence[Mapping[str, Any]] = SPRE_OPENFIGI_REIT_OBSERVATIONS,
) -> EconomicIngestPlan:
    """Dry-run only. Name and SPRE membership are never evidence."""
    _ = spre_membership_is_not_evidence("SPRE")
    official = _official_by_ticker(official_holdings)
    existing = {
        (
            str(row.get("identifier") or "").strip().upper(),
            str(row.get("identifier_type") or "").strip().upper(),
            str(row.get("source") or "").strip(),
        ): row
        for row in (existing_rows or ())
    }
    plan = EconomicIngestPlan(unmapped=max(0, len(official_holdings) - len(observations)))
    reasons: list[str] = []
    if not may_persist_reit_economic():
        reasons.append(persist_economic_blocked_reason() or "ECONOMIC_REIT_PERSIST_DISABLED")
    for raw in observations:
        ticker = listing_identity(raw.get("ticker"))
        sedol = str(raw.get("sedol") or "").strip().upper()
        figi = str(raw.get("figi") or "").strip().upper()
        weight = float(raw.get("weight_pct") or 0.0)
        name_is_not_evidence(raw.get("security_name"))
        classify_from_name_or_fund(raw.get("security_name"), "SPRE")
        holding = official.get(ticker)
        if holding is None:
            plan.unmapped += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP,
                    ticker,
                    sedol,
                    figi,
                    "",
                    "",
                    SOURCE_PROVIDER_EXPLICIT,
                    "",
                    weight,
                    "OFFICIAL_TICKER_MISSING",
                )
            )
            continue
        assessed = assess_identifier(holding.cusip_raw)
        if assessed.identifier != sedol or assessed.identifier_type != "SEDOL":
            plan.ambiguous += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP,
                    ticker,
                    sedol,
                    figi,
                    "",
                    "",
                    SOURCE_PROVIDER_EXPLICIT,
                    "",
                    weight,
                    "SEDOL_NOT_EXACT",
                )
            )
            continue
        if not is_explicit_structured_reit(raw.get("security_type"), raw.get("security_type2")):
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP,
                    ticker,
                    sedol,
                    figi,
                    "",
                    "",
                    SOURCE_PROVIDER_EXPLICIT,
                    "",
                    weight,
                    "REIT_TOKEN_NOT_EXPLICIT",
                )
            )
            continue
        if not figi:
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP,
                    ticker,
                    sedol,
                    figi,
                    "",
                    "",
                    SOURCE_PROVIDER_EXPLICIT,
                    "",
                    weight,
                    "FIGI_MISSING",
                )
            )
            continue
        canonical = canonical_id_from_figi(figi)
        observed_at = str(raw.get("observed_at") or "")
        classification = EconomicClassification(
            canonical_id=canonical,
            economic_layer="real_estate",
            source=SOURCE_PROVIDER_EXPLICIT,
            evidence_type=EVIDENCE_OPENFIGI_SECURITY_TYPE,
            evidence_reference=EVIDENCE_OPENFIGI_MAPPING,
            status=RESOLUTION_RESOLVED,
            observed_at=observed_at,
            metadata={
                "figi": figi,
                "sedol": sedol,
                "securityType": raw.get("security_type"),
                "securityType2": raw.get("security_type2"),
            },
        )
        facts = (
            economic_fact(
                identifier=ticker,
                identifier_type=IDENTIFIER_TYPE_TICKER,
                classification=classification,
            ),
            alias_fact(
                identifier=sedol,
                identifier_type=IDENTIFIER_TYPE_SEDOL,
                canonical_id=canonical,
                observed_at=observed_at,
                metadata={"figi": figi, "ticker": ticker},
            ),
        )
        if any(fact.instrument_type != "UNKNOWN" for fact in facts):
            reasons.append("INSTRUMENT_TYPE_NOT_UNKNOWN")
        all_noop = True
        for fact in facts:
            key = (fact.identifier, fact.identifier_type, fact.source)
            current = existing.get(key)
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
            if current is None or not facts_content_equal(current, payload):
                all_noop = False
                break
        plan.exact += 1
        plan.rows.append(
            EconomicIngestPlanRow(
                ACTION_NOOP if all_noop else ACTION_INSERT,
                ticker,
                sedol,
                figi,
                "UNKNOWN",
                "real_estate",
                SOURCE_PROVIDER_EXPLICIT,
                f"{raw.get('security_type')}/{raw.get('security_type2')}",
                weight,
                "IDEMPOTENT" if all_noop else "NEW_ECONOMIC_REAL_ESTATE",
                facts=facts,
            )
        )
    if plan.ambiguous:
        reasons.append("AMBIGUOUS_IDENTIFIER")
    if any(row.action == ACTION_SKIP and row.reason != "OFFICIAL_TICKER_MISSING" for row in plan.rows):
        reasons.append("SKIPPED_OBSERVATION")
    if plan.exact != len(observations):
        reasons.append("INCOMPLETE_EXACT_SET")
    plan.write_gate_reasons = tuple(dict.fromkeys(reasons))
    plan.write_gate = WRITE_GATE_PASS if not plan.write_gate_reasons else WRITE_GATE_FAIL
    return plan


def persist_economic_ingest_plan(
    plan: EconomicIngestPlan,
    *,
    security_master: SecurityMasterService,
) -> PersistFactsResult:
    if plan.write_gate != WRITE_GATE_PASS:
        raise RuntimeError(f"economic ingest write gate failed: {plan.write_gate_reasons}")
    facts = plan.facts
    if any(fact.instrument_type != "UNKNOWN" for fact in facts):
        raise RuntimeError("refusing to persist non-UNKNOWN instrument_type")
    if any(fact.source not in {SOURCE_IDENTIFIER_ALIAS, SOURCE_ECONOMIC_CLASSIFICATION} for fact in facts):
        raise RuntimeError("refusing to persist non-identity source")
    return security_master.repo.persist_facts(facts)
