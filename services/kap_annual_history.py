"""Canonical KAP annual (FY) history for the existing SecurityFacts path.

Does not invent FCF, ROIC, TTM, or interest-bearing debt.
Official KAP EPS is ingested only when the share/quote unit is explicit.
Does not mix consolidated and standalone series.
Does not persist SI, Participation, or portfolio state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from services.kap_financial_bridge import (
    KapIdentityError,
    is_us_symbol_blocked_from_kap,
    kap_security_facts_payload,
)
from services.kap_financial_contract import (
    CONSOLIDATION_UNKNOWN,
    PERIOD_FY,
    PERIOD_Q,
    PERIOD_YTD,
    KapNormalizedBundle,
)
from services.kap_financial_normalization import fy_facts_only
from services.kap_public_bridge import ingest_public_kap_financials
from services.kap_public_contract import (
    COLUMN_COMPARATIVE,
    COLUMN_CURRENT,
    DEDUP_KEY_FIELDS,
    REFRESH_KEY_KNOWN_NOTIFICATION,
    KapPublicFinancialDocument,
)
from services.kap_public_fr_discovery import classify_kap_period_label


STATUS_FOUND = "FOUND"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_INCOMPATIBLE = "INCOMPATIBLE_REPORTING_BASIS"
STATUS_PARSE_FAILED = "PARSE_FAILED"

COMPARABILITY_BREAK = "COMPARABILITY_BREAK"
RESTATEMENT_AMBIGUOUS = "RESTATEMENT_AMBIGUOUS"
RESTATED = "RESTATED"
AUTHORITATIVE_CURRENT = "AUTHORITATIVE_CURRENT"
COMPARATIVE_EVIDENCE = "COMPARATIVE_EVIDENCE"

READY = "READY"
PARTIAL = "PARTIAL"
BLOCKED = "BLOCKED"
NOT_USED = "NOT_USED"

AVAILABLE_CANONICAL = "AVAILABLE_CANONICAL"
AVAILABLE_RAW_ONLY = "AVAILABLE_RAW_ONLY"
NOT_AVAILABLE = "NOT_AVAILABLE"
METHODOLOGY_UNRESOLVED = "METHODOLOGY_UNRESOLVED"

INVENTORY_FIELDS = (
    "revenue",
    "operating_income",
    "net_income",
    "gross_profit",
    "assets",
    "equity",
    "cash",
    "current_assets",
    "current_liabilities",
    "trade_receivables",
    "ocf",
    "capex",
    "debt",
    "fcf",
    "roic",
)

CANONICAL_FACT_FIELDS = (
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "equity",
    "cash",
    "current_assets",
    "current_liabilities",
    "accounts_receivable",
)

GROWTH_PAYLOAD_FIELDS = ("revenue_growth_yoy", "revenue_cagr_3y")

RAW_ONLY_CONCEPTS = {
    "gross_profit": ("IFRS-FULL_GROSSPROFIT", "KAP-FR_GROSSPROFIT"),
    "ocf": (
        "IFRS-FULL_CASHFLOWSFROMUSEDINOPERATINGACTIVITIES",
        "IFRS-FULL_NETCASHFLOWSFROMUSEDINOPERATINGACTIVITIES",
    ),
    "capex": (
        "IFRS-FULL_PURCHASEOFPROPERTYPLANTANDEQUIPMENT",
        "IFRS-FULL_PURCHASEOFPROPERTYPLANTANDEQUIPMENTCLASIFIEDASINVESTINGACTIVITIES",
    ),
    "eps": (
        "IFRS-FULL_BASICEARNINGSLOSSPERSHARE",
        "IFRS-FULL_DILUTEDEARNINGSLOSSPERSHARE",
    ),
}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _year_of(period_end: Optional[str], report_year: Optional[str] = None) -> Optional[int]:
    if report_year and str(report_year).isdigit():
        return int(report_year)
    text = str(period_end or "")
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def yoy_growth(latest: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Existing approved YoY formula (same as SEC financial client)."""
    if latest is None or previous is None or previous == 0:
        return None
    return (latest - previous) / abs(previous) * 100


def cagr(latest: Optional[float], previous: Optional[float], years: int) -> Optional[float]:
    """Existing approved CAGR formula (same as SEC financial client)."""
    if latest is None or previous is None or years <= 0:
        return None
    if latest <= 0 or previous <= 0:
        return None
    return ((latest / previous) ** (1 / years) - 1) * 100


def document_period_kind(document: KapPublicFinancialDocument) -> str:
    label = classify_kap_period_label(document.report_period_label)
    if label in {PERIOD_FY, PERIOD_YTD, PERIOD_Q}:
        return label
    kinds = {row.period_kind for row in document.rows if row.current_period}
    if PERIOD_FY in kinds and PERIOD_YTD not in kinds and PERIOD_Q not in kinds:
        return PERIOD_FY
    if PERIOD_YTD in kinds:
        return PERIOD_YTD
    if PERIOD_Q in kinds:
        return PERIOD_Q
    return label


@dataclass(frozen=True)
class KapAnnualEvidence:
    symbol: str
    notification_id: str
    submission_date: str
    year: int
    period: str
    period_start: Optional[str]
    period_end: Optional[str]
    consolidation: str
    presentation_currency: str
    scale: str
    source_url: str
    observed_at: str
    column: str
    facts: dict[str, float]
    reported_in_notification: str
    fiscal_period: str
    provenance: str
    concepts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "notification_id": self.notification_id,
            "submission_date": self.submission_date,
            "year": self.year,
            "period": self.period,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "consolidation": self.consolidation,
            "presentation_currency": self.presentation_currency,
            "scale": self.scale,
            "source_url": self.source_url,
            "observed_at": self.observed_at,
            "column": self.column,
            "facts": dict(self.facts),
            "reported_in_notification": self.reported_in_notification,
            "fiscal_period": self.fiscal_period,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class KapAnnualYear:
    year: int
    consolidation: str
    notification_id: str
    submission_date: str
    period_start: Optional[str]
    period_end: Optional[str]
    presentation_currency: str
    scale: str
    source_url: str
    facts: dict[str, float]
    derived: dict[str, float]
    provenance: str
    warnings: tuple[str, ...] = ()
    bundle: Optional[KapNormalizedBundle] = None
    evidence_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "consolidation": self.consolidation,
            "notification_id": self.notification_id,
            "submission_date": self.submission_date,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "presentation_currency": self.presentation_currency,
            "scale": self.scale,
            "source_url": self.source_url,
            "facts": dict(self.facts),
            "derived": dict(self.derived),
            "provenance": self.provenance,
            "warnings": list(self.warnings),
            "evidence_count": self.evidence_count,
        }


@dataclass(frozen=True)
class KapAnnualHistory:
    symbol: str
    reporting_basis: str
    years: tuple[KapAnnualYear, ...]
    evidence: tuple[KapAnnualEvidence, ...]
    rejected: tuple[dict[str, Any], ...]
    comparability_breaks: tuple[dict[str, Any], ...]
    restatements: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    cell_status: dict[int, str] = field(default_factory=dict)

    def canonical_years(self) -> tuple[KapAnnualYear, ...]:
        return tuple(
            item
            for item in self.years
            if item.consolidation == self.reporting_basis or not self.reporting_basis
        )

    def year_map(self) -> dict[int, KapAnnualYear]:
        return {item.year: item for item in self.canonical_years()}

    def latest(self) -> Optional[KapAnnualYear]:
        canonical = self.canonical_years()
        return canonical[-1] if canonical else None

    def series(self, field: str) -> list[tuple[int, float]]:
        out: list[tuple[int, float]] = []
        for item in self.canonical_years():
            value = item.facts.get(field)
            if value is not None:
                out.append((item.year, value))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "reporting_basis": self.reporting_basis,
            "years": [item.to_dict() for item in self.years],
            "evidence": [item.to_dict() for item in self.evidence],
            "rejected": list(self.rejected),
            "comparability_breaks": list(self.comparability_breaks),
            "restatements": list(self.restatements),
            "warnings": list(self.warnings),
            "cell_status": {str(year): status for year, status in self.cell_status.items()},
            "refresh_key": REFRESH_KEY_KNOWN_NOTIFICATION,
            "dedup_key": list(DEDUP_KEY_FIELDS),
        }


def _prefer_numeric(existing: Optional[float], incoming: float) -> float:
    """Keep a real FY amount when a later empty/zero taxonomy row would overwrite it."""
    if existing is None:
        return incoming
    if existing == 0 and incoming != 0:
        return incoming
    return existing


def _facts_from_bundle(bundle: KapNormalizedBundle) -> dict[str, float]:
    facts: dict[str, float] = {}
    for item in fy_facts_only(bundle.mapped):
        facts[item.field] = _prefer_numeric(facts.get(item.field), item.normalized_value)
    return facts


def _derived_from_facts(facts: dict[str, float]) -> dict[str, float]:
    """Existing KAP ratio rules on cleaned FY facts. No new methodology."""
    derived: dict[str, float] = {}
    net_income = facts.get("net_income")
    assets = facts.get("total_assets")
    equity = facts.get("equity")
    debt = facts.get("total_debt")
    current_assets = facts.get("current_assets")
    current_liabilities = facts.get("current_liabilities")
    if net_income is not None and assets not in (None, 0):
        derived["roa"] = net_income / assets * 100.0
    if net_income is not None and equity not in (None, 0):
        derived["roe"] = net_income / equity * 100.0
    if debt is not None and equity not in (None, 0):
        derived["debt_to_equity"] = debt / equity
    if current_assets is not None and current_liabilities not in (None, 0):
        derived["current_ratio"] = current_assets / current_liabilities
    return derived


def _derived_from_bundle(bundle: KapNormalizedBundle) -> dict[str, float]:
    cleaned = _facts_from_bundle(bundle)
    derived = _derived_from_facts(cleaned)
    if derived:
        return derived
    fallback: dict[str, float] = {}
    for item in bundle.derived:
        if item.value is None or item.period_compatibility != PERIOD_FY:
            continue
        fallback[item.field] = item.value
    return fallback


def _evidence_from_document(
    document: KapPublicFinancialDocument,
    *,
    current_period: bool,
    observed_at: str,
) -> Optional[KapAnnualEvidence]:
    rows = tuple(row for row in document.rows if row.current_period is current_period)
    if not rows:
        return None
    fy_rows = tuple(row for row in rows if row.period_kind == PERIOD_FY)
    if not fy_rows:
        return None
    sliced = replace(document, rows=fy_rows)
    bundle = ingest_public_kap_financials(sliced, symbol=document.symbol)
    facts = _facts_from_bundle(bundle)
    if not facts:
        return None
    year = _year_of(
        next((row.period_end for row in fy_rows if row.period_end), None),
        document.report_year if current_period else None,
    )
    if year is None:
        return None
    flow = next((row for row in fy_rows if row.period_start and row.period_end), None)
    column = COLUMN_CURRENT if current_period else COLUMN_COMPARATIVE
    return KapAnnualEvidence(
        symbol=document.symbol.upper(),
        notification_id=document.disclosure_id,
        submission_date=document.published_at or "",
        year=year,
        period=PERIOD_FY,
        period_start=flow.period_start if flow else None,
        period_end=flow.period_end if flow else next((row.period_end for row in fy_rows), None),
        consolidation=document.consolidation or CONSOLIDATION_UNKNOWN,
        presentation_currency=document.presentation_currency,
        scale=document.presentation_unit_label,
        source_url=document.source_url,
        observed_at=observed_at,
        column=column,
        facts=facts,
        reported_in_notification=document.disclosure_id,
        fiscal_period=f"{year} FY",
        provenance=AUTHORITATIVE_CURRENT if current_period else COMPARATIVE_EVIDENCE,
        concepts=tuple(document.observed_concepts),
    )


def _sort_key(item: KapAnnualEvidence) -> tuple[str, str, int]:
    current_rank = 1 if item.column == COLUMN_CURRENT else 0
    return (item.submission_date, item.notification_id, current_rank)


def _select_authoritative(
    rows: list[KapAnnualEvidence],
) -> tuple[KapAnnualEvidence, tuple[str, ...], Optional[dict[str, Any]]]:
    ordered = sorted(rows, key=_sort_key)
    latest = ordered[-1]
    warnings: list[str] = []
    restatement: Optional[dict[str, Any]] = None
    values = {
        (item.notification_id, item.column): item.facts.get("revenue")
        for item in ordered
        if item.facts.get("revenue") is not None
    }
    distinct = {value for value in values.values()}
    if len(ordered) > 1 and len(distinct) > 1:
        ids = {item.notification_id for item in ordered}
        dates = {item.submission_date for item in ordered if item.submission_date}
        same_explicit_date = len(dates) == 1
        if same_explicit_date or len(ids) == 1:
            warnings.append(RESTATEMENT_AMBIGUOUS)
            restatement = {
                "year": latest.year,
                "status": RESTATEMENT_AMBIGUOUS,
                "notification_ids": [item.notification_id for item in ordered],
            }
        else:
            warnings.append(RESTATED)
            restatement = {
                "year": latest.year,
                "status": RESTATED,
                "authoritative_notification": latest.notification_id,
                "superseded": [
                    item.notification_id
                    for item in ordered
                    if item.notification_id != latest.notification_id
                ],
            }
    return latest, tuple(warnings), restatement


def build_kap_annual_history(
    symbol: str,
    documents: Iterable[KapPublicFinancialDocument],
    *,
    target_years: tuple[int, ...] = (2022, 2023, 2024, 2025),
    observed_at: str = "",
) -> KapAnnualHistory:
    ticker = str(symbol or "").upper()
    if is_us_symbol_blocked_from_kap(ticker):
        raise KapIdentityError(ticker)
    documents = tuple(documents)
    observed = observed_at or _today()
    evidence: list[KapAnnualEvidence] = []
    rejected: list[dict[str, Any]] = []
    for document in documents:
        kind = document_period_kind(document)
        if kind != PERIOD_FY:
            rejected.append(
                {
                    "notification_id": document.disclosure_id,
                    "period_kind": kind,
                    "reason": "REJECTED_NON_FY",
                }
            )
            continue
        try:
            current = _evidence_from_document(document, current_period=True, observed_at=observed)
            comparative = _evidence_from_document(
                document, current_period=False, observed_at=observed
            )
        except Exception as exc:  # parse/normalize fail-closed for this filing
            rejected.append(
                {
                    "notification_id": document.disclosure_id,
                    "period_kind": kind,
                    "reason": STATUS_PARSE_FAILED,
                    "detail": type(exc).__name__,
                }
            )
            continue
        if current is not None:
            evidence.append(current)
        if comparative is not None:
            evidence.append(comparative)
        if current is None and comparative is None:
            rejected.append(
                {
                    "notification_id": document.disclosure_id,
                    "period_kind": kind,
                    "reason": STATUS_PARSE_FAILED,
                }
            )

    preferred = ""
    current_only = [item for item in evidence if item.column == COLUMN_CURRENT]
    if current_only:
        preferred = sorted(current_only, key=_sort_key)[-1].consolidation

    grouped: dict[tuple[int, str], list[KapAnnualEvidence]] = {}
    for item in evidence:
        grouped.setdefault((item.year, item.consolidation), []).append(item)

    years: list[KapAnnualYear] = []
    restatements: list[dict[str, Any]] = []
    breaks: list[dict[str, Any]] = []
    warnings: list[str] = []
    cell_status: dict[int, str] = {year: STATUS_NOT_FOUND for year in target_years}

    for (year, basis), rows in sorted(grouped.items()):
        if target_years and year not in target_years:
            continue
        chosen, year_warnings, restatement = _select_authoritative(rows)
        warnings.extend(year_warnings)
        if restatement is not None:
            restatements.append(restatement)
        try:
            source_doc = next(
                document
                for document in documents
                if document.disclosure_id == chosen.notification_id
            )
            fy_rows = tuple(
                row
                for row in source_doc.rows
                if row.period_kind == PERIOD_FY and row.current_period == (chosen.column == COLUMN_CURRENT)
            )
            bundle = ingest_public_kap_financials(replace(source_doc, rows=fy_rows), symbol=ticker)
        except Exception:
            bundle = None
        years.append(
            KapAnnualYear(
                year=year,
                consolidation=basis,
                notification_id=chosen.notification_id,
                submission_date=chosen.submission_date,
                period_start=chosen.period_start,
                period_end=chosen.period_end,
                presentation_currency=chosen.presentation_currency,
                scale=chosen.scale,
                source_url=chosen.source_url,
                facts=dict(chosen.facts),
                derived=_derived_from_bundle(bundle) if bundle is not None else {},
                provenance=chosen.provenance,
                warnings=year_warnings,
                bundle=bundle,
                evidence_count=len(rows),
            )
        )
        if year in cell_status:
            if preferred and basis != preferred:
                cell_status[year] = STATUS_INCOMPATIBLE
                breaks.append(
                    {
                        "year": year,
                        "status": COMPARABILITY_BREAK,
                        "reporting_basis": basis,
                        "preferred_basis": preferred,
                        "notification_id": chosen.notification_id,
                    }
                )
                warnings.append(COMPARABILITY_BREAK)
            else:
                cell_status[year] = STATUS_FOUND

    for item in rejected:
        if item.get("reason") == STATUS_PARSE_FAILED:
            year = _year_of(None, str(item.get("year") or ""))
            if year in cell_status and cell_status[year] == STATUS_NOT_FOUND:
                cell_status[year] = STATUS_PARSE_FAILED

    years.sort(key=lambda item: item.year)
    return KapAnnualHistory(
        symbol=ticker,
        reporting_basis=preferred,
        years=tuple(years),
        evidence=tuple(evidence),
        rejected=tuple(rejected),
        comparability_breaks=tuple(breaks),
        restatements=tuple(restatements),
        warnings=tuple(dict.fromkeys(warnings)),
        cell_status=cell_status,
    )


def comparable_field_series(history: KapAnnualHistory, field: str) -> list[tuple[int, float]]:
    broken = {int(item["year"]) for item in history.comparability_breaks}
    return [(year, value) for year, value in history.series(field) if year not in broken]


def growth_readiness(history: KapAnnualHistory) -> dict[str, str]:
    revenue = comparable_field_series(history, "revenue")
    years = {year for year, _ in revenue}
    latest = history.latest()
    yoy = BLOCKED
    cagr3 = BLOCKED
    if latest is not None and (latest.year - 1) in years and latest.year in years:
        yoy = READY
    if latest is not None and (latest.year - 3) in years and latest.year in years:
        cagr3 = READY
    return {
        "revenue_growth_yoy": yoy,
        "revenue_cagr_3y": cagr3,
        "eps_growth_yoy": BLOCKED,
        "eps_cagr_3y": BLOCKED,
        "fcf_cagr_3y": BLOCKED,
    }


def safe_growth_fields(history: KapAnnualHistory) -> dict[str, float]:
    revenue = comparable_field_series(history, "revenue")
    by_year = dict(revenue)
    latest = history.latest()
    out: dict[str, float] = {}
    if latest is None:
        return out
    prior = by_year.get(latest.year - 1)
    current = by_year.get(latest.year)
    yoy = yoy_growth(current, prior)
    if yoy is not None:
        out["revenue_growth_yoy"] = yoy
    base = by_year.get(latest.year - 3)
    three = cagr(current, base, 3)
    if three is not None:
        out["revenue_cagr_3y"] = three
    return out


def quality_readiness(history: KapAnnualHistory) -> dict[str, str]:
    latest = history.latest()
    derived = latest.derived if latest is not None else {}
    facts = latest.facts if latest is not None else {}
    return {
        "ROE": READY if derived.get("roe") is not None else BLOCKED,
        "ROA": READY if derived.get("roa") is not None else BLOCKED,
        "ROIC": NOT_USED,
        "operating_margin": BLOCKED,
        "net_margin": BLOCKED,
        "gross_margin": BLOCKED,
        "fcf_margin": NOT_USED,
        "current_ratio": READY if derived.get("current_ratio") is not None else BLOCKED,
        "debt_to_equity": READY if derived.get("debt_to_equity") is not None else BLOCKED,
        "net_debt_to_fcf": BLOCKED,
        "interest_coverage": BLOCKED,
        "_has_revenue": READY if facts.get("revenue") is not None else BLOCKED,
    }


def inventory_annual_facts(
    history: KapAnnualHistory,
    *,
    observed_concepts: Iterable[str] = (),
) -> dict[str, str]:
    latest = history.latest()
    facts = latest.facts if latest is not None else {}
    concepts = {str(item).upper() for item in observed_concepts}
    if latest is not None:
        for item in history.evidence:
            if item.year == latest.year:
                concepts.update(code.upper() for code in item.concepts)
    inventory = {
        "revenue": AVAILABLE_CANONICAL if facts.get("revenue") is not None else NOT_AVAILABLE,
        "operating_income": AVAILABLE_CANONICAL if facts.get("operating_income") is not None else NOT_AVAILABLE,
        "net_income": AVAILABLE_CANONICAL if facts.get("net_income") is not None else NOT_AVAILABLE,
        "assets": AVAILABLE_CANONICAL if facts.get("total_assets") is not None else NOT_AVAILABLE,
        "equity": AVAILABLE_CANONICAL if facts.get("equity") is not None else NOT_AVAILABLE,
        "cash": AVAILABLE_CANONICAL if facts.get("cash") is not None else NOT_AVAILABLE,
        "current_assets": AVAILABLE_CANONICAL if facts.get("current_assets") is not None else NOT_AVAILABLE,
        "current_liabilities": AVAILABLE_CANONICAL if facts.get("current_liabilities") is not None else NOT_AVAILABLE,
        "trade_receivables": AVAILABLE_CANONICAL if facts.get("accounts_receivable") is not None else NOT_AVAILABLE,
        "gross_profit": AVAILABLE_RAW_ONLY if any(code in concepts for code in RAW_ONLY_CONCEPTS["gross_profit"]) else NOT_AVAILABLE,
        "ocf": AVAILABLE_RAW_ONLY if any(code in concepts for code in RAW_ONLY_CONCEPTS["ocf"]) else NOT_AVAILABLE,
        "capex": AVAILABLE_RAW_ONLY if any(code in concepts for code in RAW_ONLY_CONCEPTS["capex"]) else NOT_AVAILABLE,
        "debt": NOT_AVAILABLE,
        "fcf": METHODOLOGY_UNRESOLVED,
        "roic": NOT_AVAILABLE,
        "eps": (
            AVAILABLE_CANONICAL
            if facts.get("eps") is not None
            else AVAILABLE_RAW_ONLY
            if any(code in concepts for code in RAW_ONLY_CONCEPTS["eps"])
            else NOT_AVAILABLE
        ),
    }
    return inventory


def kap_security_facts_payload_from_history(history: KapAnnualHistory) -> dict[str, Any]:
    latest = history.latest()
    if latest is None or latest.bundle is None:
        payload = {
            "symbol": history.symbol,
            "currency": "",
            "financial_period_end": None,
            "period_kind": PERIOD_FY,
            "source": "kap_normalized",
        }
    else:
        payload = kap_security_facts_payload(latest.bundle)
    if latest is not None:
        payload.update(latest.facts)
        payload.update(latest.derived)
        payload["financial_period_end"] = payload.get("financial_period_end") or latest.period_end
        payload["currency"] = payload.get("currency") or latest.presentation_currency
    payload.update(safe_growth_fields(history))
    return payload
