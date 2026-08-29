"""Plan and persist economic classification + identifier aliases.

Does not write instrument_type REIT or SUKUK. Does not change Participation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from repositories.security_master_repository import PersistFactsResult, facts_content_equal
from services.official_fund_holdings_client import OfficialHolding
from services.openfigi_client import MATCH_EXACT_SINGLE, MATCH_MULTIPLE, MATCH_NONE
from services.reit_evidence_contract import (
    is_explicit_structured_reit,
    listing_equity_is_not_reit,
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
    IDENTIFIER_TYPE_CUSIP,
    IDENTIFIER_TYPE_SEDOL,
    IDENTIFIER_TYPE_TICKER,
    INSTRUMENT_EQUITY,
    RESOLUTION_CONFLICT,
    RESOLUTION_RESOLVED,
    SOURCE_US_LISTING,
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

US_REIT_ONBOARDING_TARGETS = (
    "WELL",
    "PLD",
    "EQIX",
    "O",
    "AMT",
    "SPG",
    "DLR",
    "PSA",
)

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


def collect_us_listing_identity(
    master: SecurityMasterService,
    ticker: Any,
    *,
    official_cusip: str = "",
    official_sedol: str = "",
    official_isin: str = "",
) -> dict[str, Any]:
    """Exact Security Master listing identity. No name or sector joins."""
    ident = listing_identity(ticker)
    if not ident:
        return {
            "ticker": "",
            "identity_status": "unmapped",
            "instrument_type": "",
            "source": "",
            "exchange": "",
            "cusip": "",
            "sedol": "",
            "isin": "",
            "figi": "",
            "issuer_name": "",
            "sm_row": False,
            "reason": "EMPTY_TICKER",
        }
    facts = master.get_security_facts(ident, identifier_type=IDENTIFIER_TYPE_TICKER)
    listing_facts = [row for row in facts if row.source == SOURCE_US_LISTING]
    resolved = master.resolve_security(ident)
    cusip = ""
    sedol = ""
    isin = ""
    figi = ""
    assessed_cusip = assess_identifier(official_cusip)
    if assessed_cusip.identifier_type == IDENTIFIER_TYPE_CUSIP:
        cusip = assessed_cusip.identifier or ""
    assessed_sedol = assess_identifier(official_sedol)
    if assessed_sedol.identifier_type == IDENTIFIER_TYPE_SEDOL:
        sedol = assessed_sedol.identifier or ""
    assessed_isin = assess_identifier(official_isin)
    if assessed_isin.identifier_type == "ISIN":
        isin = assessed_isin.identifier or ""
    for fact in facts:
        meta = dict(fact.metadata or {})
        if not cusip:
            extra = assess_identifier(meta.get("cusip"))
            if extra.identifier_type == IDENTIFIER_TYPE_CUSIP:
                cusip = extra.identifier or ""
        if not sedol:
            extra = assess_identifier(meta.get("sedol"))
            if extra.identifier_type == IDENTIFIER_TYPE_SEDOL:
                sedol = extra.identifier or ""
        if not isin:
            extra = assess_identifier(meta.get("isin"))
            if extra.identifier_type == "ISIN":
                isin = extra.identifier or ""
        if not figi:
            figi = str(meta.get("figi") or "").strip().upper()
    listing = listing_facts[0] if listing_facts else None
    if resolved.status == RESOLUTION_CONFLICT or len(listing_facts) > 1:
        status = "ambiguous"
        reason = "IDENTITY_CONFLICT"
    elif listing is None:
        status = "unmapped"
        reason = resolved.limitation or "NO_US_LISTING"
    else:
        status = "exact"
        reason = "US_LISTING"
    return {
        "ticker": ident,
        "identity_status": status,
        "instrument_type": (
            listing.instrument_type if listing is not None else resolved.instrument_type
        ),
        "source": listing.source if listing is not None else (resolved.source or ""),
        "exchange": (listing.exchange if listing is not None else "") or "",
        "cusip": cusip,
        "sedol": sedol,
        "isin": isin,
        "figi": figi,
        "issuer_name": (listing.issuer_name if listing is not None else "") or "",
        "sm_row": listing is not None,
        "observed_at": (listing.observed_at if listing is not None else "") or "",
        "reason": reason,
    }


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


def _qualification_map(
    qualifications: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    if isinstance(qualifications, Mapping) and "ticker" not in qualifications:
        return {
            listing_identity(key): (
                value.to_dict() if hasattr(value, "to_dict") else dict(value)
            )
            for key, value in qualifications.items()
        }
    mapped: dict[str, Mapping[str, Any]] = {}
    for raw in qualifications:
        row = raw.to_dict() if hasattr(raw, "to_dict") else dict(raw)
        ticker = listing_identity(row.get("ticker") or row.get("symbol"))
        if ticker:
            mapped[ticker] = row
    return mapped


def _existing_fact_index(
    existing_rows: Sequence[Mapping[str, Any]] | None,
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    return {
        (
            str(row.get("identifier") or "").strip().upper(),
            str(row.get("identifier_type") or "").strip().upper(),
            str(row.get("source") or "").strip(),
        ): row
        for row in (existing_rows or ())
    }


def _facts_already_present(
    facts: Sequence[SecurityFact],
    existing: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> bool:
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
            return False
    return True


def _alias_if_exact(
    raw: Any,
    *,
    expected_type: str,
    canonical_id: str,
    observed_at: str,
    metadata: Mapping[str, Any],
) -> Optional[SecurityFact]:
    assessed = assess_identifier(raw)
    if assessed.identifier and assessed.identifier_type == expected_type:
        return alias_fact(
            identifier=assessed.identifier,
            identifier_type=expected_type,
            canonical_id=canonical_id,
            observed_at=observed_at,
            metadata=metadata,
        )
    return None


def plan_us_listing_reit_economic_ingest(
    identities: Sequence[Mapping[str, Any]],
    qualifications: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    existing_rows: Sequence[Mapping[str, Any]] | None = None,
) -> EconomicIngestPlan:
    """Persist economic real_estate for exact US listings with explicit REIT tokens.

    Listing instrument_type stays EQUITY. Names and sector labels are not evidence.
    Failed candidates stay SKIP and do not block writes for PASS rows.
    """
    qual_by_ticker = _qualification_map(qualifications)
    existing = _existing_fact_index(existing_rows)
    plan = EconomicIngestPlan()
    reasons: list[str] = []
    if not may_persist_reit_economic():
        reasons.append(persist_economic_blocked_reason() or "ECONOMIC_REIT_PERSIST_DISABLED")
    for raw in identities:
        ticker = listing_identity(raw.get("ticker") or raw.get("symbol"))
        name_is_not_evidence(raw.get("issuer_name") or raw.get("security_name"))
        classify_from_name_or_fund(raw.get("issuer_name") or raw.get("security_name"), "")
        instrument = str(raw.get("instrument_type") or "").strip().upper()
        source = str(raw.get("source") or "").strip()
        identity_status = str(raw.get("identity_status") or "").strip().lower()
        cusip = str(raw.get("cusip") or "").strip().upper()
        sedol = str(raw.get("sedol") or "").strip().upper()
        figi = ""
        if not ticker:
            plan.unmapped += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, "", "", "", "", "", SOURCE_PROVIDER_EXPLICIT, "", 0.0,
                    "EMPTY_TICKER",
                )
            )
            continue
        if identity_status == "unmapped" or not instrument:
            plan.unmapped += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, "", instrument, "", SOURCE_PROVIDER_EXPLICIT, "",
                    0.0, "IDENTITY_UNMAPPED",
                )
            )
            continue
        if identity_status == "ambiguous":
            plan.ambiguous += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, "", instrument, "", SOURCE_PROVIDER_EXPLICIT, "",
                    0.0, "IDENTITY_AMBIGUOUS",
                )
            )
            continue
        if not listing_equity_is_not_reit(instrument, source=source):
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, "", instrument, "", source, "", 0.0,
                    "LISTING_NOT_US_EQUITY",
                )
            )
            continue
        qual = dict(qual_by_ticker.get(ticker) or {})
        match_status = str(qual.get("match_status") or "").strip()
        figi = str(qual.get("figi") or "").strip().upper()
        security_type = qual.get("securityType") or qual.get("security_type") or ""
        security_type2 = qual.get("securityType2") or qual.get("security_type2") or ""
        provider_ticker = listing_identity(qual.get("ticker") or qual.get("provider_ticker"))
        if match_status == MATCH_MULTIPLE:
            plan.ambiguous += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, figi, instrument, "", SOURCE_PROVIDER_EXPLICIT, "",
                    0.0, "OPENFIGI_MULTIPLE",
                )
            )
            continue
        if match_status in {MATCH_NONE, ""}:
            plan.unmapped += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, figi, instrument, "", SOURCE_PROVIDER_EXPLICIT, "",
                    0.0, "OPENFIGI_UNMAPPED",
                )
            )
            continue
        if match_status != MATCH_EXACT_SINGLE:
            plan.unmapped += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, figi, instrument, "", SOURCE_PROVIDER_EXPLICIT, "",
                    0.0, match_status or "OPENFIGI_NOT_EXACT",
                )
            )
            continue
        if provider_ticker and provider_ticker != ticker:
            plan.ambiguous += 1
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, figi, instrument, "", SOURCE_PROVIDER_EXPLICIT, "",
                    0.0, "OPENFIGI_TICKER_MISMATCH",
                )
            )
            continue
        if not is_explicit_structured_reit(security_type, security_type2):
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, figi, instrument, "", SOURCE_PROVIDER_EXPLICIT,
                    f"{security_type}/{security_type2}", 0.0, "REIT_TOKEN_NOT_EXPLICIT",
                )
            )
            continue
        if not figi:
            plan.rows.append(
                EconomicIngestPlanRow(
                    ACTION_SKIP, ticker, sedol, "", instrument, "", SOURCE_PROVIDER_EXPLICIT, "",
                    0.0, "FIGI_MISSING",
                )
            )
            continue
        observed_at = str(raw.get("observed_at") or qual.get("observed_at") or "")
        canonical = canonical_id_from_figi(figi)
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
                "ticker": ticker,
                "exchange": raw.get("exchange"),
                "cusip": cusip,
                "sedol": sedol,
                "securityType": security_type,
                "securityType2": security_type2,
                "listing_instrument_type": INSTRUMENT_EQUITY,
                "listing_source": SOURCE_US_LISTING,
            },
        )
        facts = [
            economic_fact(
                identifier=ticker,
                identifier_type=IDENTIFIER_TYPE_TICKER,
                classification=classification,
            )
        ]
        cusip_alias = _alias_if_exact(
            cusip,
            expected_type=IDENTIFIER_TYPE_CUSIP,
            canonical_id=canonical,
            observed_at=observed_at,
            metadata={"figi": figi, "ticker": ticker},
        )
        if cusip_alias is not None:
            facts.append(cusip_alias)
        sedol_alias = _alias_if_exact(
            sedol,
            expected_type=IDENTIFIER_TYPE_SEDOL,
            canonical_id=canonical,
            observed_at=observed_at,
            metadata={"figi": figi, "ticker": ticker},
        )
        if sedol_alias is not None:
            facts.append(sedol_alias)
        if any(fact.instrument_type != "UNKNOWN" for fact in facts):
            reasons.append("INSTRUMENT_TYPE_NOT_UNKNOWN")
        all_noop = _facts_already_present(facts, existing)
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
                f"{security_type}/{security_type2}",
                0.0,
                "IDEMPOTENT" if all_noop else "NEW_ECONOMIC_REAL_ESTATE",
                facts=tuple(facts),
            )
        )
    persistable = [row for row in plan.rows if row.action != ACTION_SKIP]
    if not persistable:
        reasons.append("NO_QUALIFYING_REIT")
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
