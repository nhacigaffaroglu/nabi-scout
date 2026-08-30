"""Raw KAP / Turkish IFRS financial-statement vocabulary.

Layer A (access) is separate from layer B (raw facts). This module does
not fetch, normalize, score, or produce Participation verdicts.

No official KAP financial-statement endpoint is documented in-repo.
KapDisclosureAdapter is a signal/disclosure contract only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from services.signal_disclosure_adapters import KapDisclosureAdapter


KAP_ACCESS_READY = "KAP_ACCESS_READY"
KAP_ACCESS_CREDENTIAL_BLOCKED = "KAP_ACCESS_CREDENTIAL_BLOCKED"
KAP_FINANCIAL_ENDPOINT_UNKNOWN = "KAP_FINANCIAL_ENDPOINT_UNKNOWN"
KAP_ACCESS_UNAVAILABLE = "KAP_ACCESS_UNAVAILABLE"

KAP_SOURCE = "KAP"

STATEMENT_INCOME = "INCOME"
STATEMENT_BALANCE = "BALANCE_SHEET"
STATEMENT_CASH_FLOW = "CASH_FLOW"

CONSOLIDATION_CONSOLIDATED = "CONSOLIDATED"
CONSOLIDATION_STANDALONE = "STANDALONE"
CONSOLIDATION_UNKNOWN = "UNKNOWN"

NATURE_POINT_IN_TIME = "POINT_IN_TIME"
NATURE_FLOW = "FLOW"

PERIOD_FY = "FY"
PERIOD_YTD = "YTD"
PERIOD_Q = "Q"
PERIOD_UNKNOWN = "UNKNOWN"

SCALE_ONE = 1
SCALE_THOUSAND = 1_000
SCALE_MILLION = 1_000_000

# Exact unit labels only. No substring guessing.
EXPLICIT_UNIT_SCALES = {
    "1": SCALE_ONE,
    "TRY": SCALE_ONE,
    "TL": SCALE_ONE,
    "THOUSAND TRY": SCALE_THOUSAND,
    "THOUSAND TL": SCALE_THOUSAND,
    "BIN TRY": SCALE_THOUSAND,
    "BIN TL": SCALE_THOUSAND,
    "1.000 TL": SCALE_THOUSAND,
    "1.000 TRY": SCALE_THOUSAND,
    "1,000 TL": SCALE_THOUSAND,
    "1,000 TRY": SCALE_THOUSAND,
    "MILLION TRY": SCALE_MILLION,
    "MILLION TL": SCALE_MILLION,
    "MILYON TRY": SCALE_MILLION,
    "MILYON TL": SCALE_MILLION,
}

# Verified public KAP / IFRS taxonomy identifiers. Not label aliases.
IFRS_REVENUE = "IFRS-FULL_REVENUE"
IFRS_OPERATING_INCOME = "IFRS-FULL_PROFITLOSSFROMOPERATINGACTIVITIES"
IFRS_NET_INCOME = "IFRS-FULL_PROFITLOSS"
IFRS_TOTAL_ASSETS = "IFRS-FULL_ASSETS"
IFRS_EQUITY = "IFRS-FULL_EQUITY"
IFRS_CASH = "IFRS-FULL_CASHANDCASHEQUIVALENTS"
IFRS_CURRENT_ASSETS = "IFRS-FULL_CURRENTASSETS"
IFRS_CURRENT_LIABILITIES = "IFRS-FULL_CURRENTLIABILITIES"

KAP_SOURCE_PUBLIC = "PUBLIC_KAP"

# Test-only taxonomy identifiers. Not official KAP/IFRS codes.
ACCOUNT_REVENUE = "NABI_TEST.IS.REVENUE"
ACCOUNT_OPERATING_INCOME = "NABI_TEST.IS.OPERATING_INCOME"
ACCOUNT_NET_INCOME = "NABI_TEST.IS.NET_INCOME"
ACCOUNT_TOTAL_ASSETS = "NABI_TEST.BS.TOTAL_ASSETS"
ACCOUNT_TOTAL_EQUITY = "NABI_TEST.BS.TOTAL_EQUITY"
ACCOUNT_CASH = "NABI_TEST.BS.CASH_AND_EQUIVALENTS"
ACCOUNT_TOTAL_DEBT = "NABI_TEST.BS.TOTAL_DEBT"
ACCOUNT_CURRENT_ASSETS = "NABI_TEST.BS.CURRENT_ASSETS"
ACCOUNT_CURRENT_LIABILITIES = "NABI_TEST.BS.CURRENT_LIABILITIES"


@dataclass(frozen=True)
class KapFinancialAccessStatus:
    status: str
    existing_adapter: str
    official_client: Optional[str]
    credentials_configured: bool
    financial_endpoint: Optional[str]
    live_calls_allowed: bool
    limitation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "existing_adapter": self.existing_adapter,
            "official_client": self.official_client,
            "credentials_configured": self.credentials_configured,
            "financial_endpoint": self.financial_endpoint,
            "live_calls_allowed": self.live_calls_allowed,
            "limitation": self.limitation,
        }


class KapFinancialAccessError(RuntimeError):
    """Official KAP financial transport is not available."""


def resolve_kap_financial_access() -> KapFinancialAccessStatus:
    """Inspect KAP wiring. Does not call KAP or invent endpoints."""
    from services.kap_rest_client import KapRestClient
    from services.kap_rest_config import load_kap_rest_config

    adapter = KapDisclosureAdapter
    config = load_kap_rest_config()
    return KapFinancialAccessStatus(
        status=KAP_ACCESS_CREDENTIAL_BLOCKED
        if not config.available
        else KAP_ACCESS_UNAVAILABLE,
        existing_adapter=f"{adapter.__name__} available={adapter.available}",
        official_client=KapRestClient.__name__,
        credentials_configured=config.available,
        financial_endpoint=None,
        live_calls_allowed=False,
        limitation=(
            "Official KAP access uses documented disclosure services "
            "(disclosures → disclosureDetail → downloadAttachment). "
            "No dedicated financial-statements endpoint is documented. "
            "Live HTTP is unbound; missing base URL/API key fail-closes. "
            f"Signal adapter remains {adapter.__name__} available={adapter.available}."
        ),
    )


def fetch_official_kap_financials(*_args: Any, **_kwargs: Any) -> None:
    """Transport is closed until an official financial endpoint is documented."""
    status = resolve_kap_financial_access()
    raise KapFinancialAccessError(status.limitation)


@dataclass(frozen=True)
class KapRawFinancialLine:
    """Official raw line. Values stay raw; normalization lives elsewhere."""

    symbol: str
    statement_type: str
    reporting_period: str
    fact_nature: str
    currency: str
    account_label: str
    source: str = KAP_SOURCE
    issuer_id: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    consolidation: str = CONSOLIDATION_UNKNOWN
    unit_scale: Optional[int] = None
    unit_label: str = ""
    account_code: Optional[str] = None
    raw_value: Optional[float] = None
    source_document_id: Optional[str] = None
    published_at: Optional[str] = None
    as_of: Optional[str] = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "issuer_id": self.issuer_id,
            "statement_type": self.statement_type,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "reporting_period": self.reporting_period,
            "fact_nature": self.fact_nature,
            "consolidation": self.consolidation,
            "currency": self.currency,
            "unit_scale": self.unit_scale,
            "unit_label": self.unit_label,
            "account_code": self.account_code,
            "account_label": self.account_label,
            "raw_value": self.raw_value,
            "source": self.source,
            "source_document_id": self.source_document_id,
            "published_at": self.published_at,
            "as_of": self.as_of,
            "provenance": dict(self.provenance or {}),
        }


@dataclass(frozen=True)
class KapNormalizedFinancialFact:
    field: str
    symbol: str
    raw_value: float
    raw_unit_scale: int
    raw_unit_label: str
    normalized_value: float
    currency: str
    normalization_rule: str
    period_kind: str
    fact_nature: str
    statement_type: str
    period_start: Optional[str]
    period_end: Optional[str]
    account_code: Optional[str]
    account_label: str
    source: str
    source_document_id: Optional[str]
    as_of: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "symbol": self.symbol,
            "raw_value": self.raw_value,
            "raw_unit_scale": self.raw_unit_scale,
            "raw_unit_label": self.raw_unit_label,
            "normalized_value": self.normalized_value,
            "currency": self.currency,
            "normalization_rule": self.normalization_rule,
            "period_kind": self.period_kind,
            "fact_nature": self.fact_nature,
            "statement_type": self.statement_type,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "account_code": self.account_code,
            "account_label": self.account_label,
            "source": self.source,
            "source_document_id": self.source_document_id,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class KapDerivedFact:
    field: str
    value: Optional[float]
    numerator_field: str
    denominator_field: str
    period_compatibility: str
    currency: str
    normalization_rule: str
    limitation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "numerator_field": self.numerator_field,
            "denominator_field": self.denominator_field,
            "period_compatibility": self.period_compatibility,
            "currency": self.currency,
            "normalization_rule": self.normalization_rule,
            "limitation": self.limitation,
        }


@dataclass(frozen=True)
class KapNormalizedBundle:
    symbol: str
    identity_source: str
    mapped: tuple[KapNormalizedFinancialFact, ...]
    unmapped_account_codes: tuple[str, ...]
    derived: tuple[KapDerivedFact, ...]
    period_compatibility: str
    limitation: str = ""

    def fact(self, field: str) -> Optional[KapNormalizedFinancialFact]:
        for item in self.mapped:
            if item.field == field:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "identity_source": self.identity_source,
            "mapped": [item.to_dict() for item in self.mapped],
            "unmapped_account_codes": list(self.unmapped_account_codes),
            "derived": [item.to_dict() for item in self.derived],
            "period_compatibility": self.period_compatibility,
            "limitation": self.limitation,
        }
