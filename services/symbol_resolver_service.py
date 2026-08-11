from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional

from config.scan_universe import PARTICIPATION_DEFAULTS, SCAN_UNIVERSES
from services.fmp_client import FMPClient, FMPError
from services.security_classifier import classify_security

RESOLUTION_HIGH = "HIGH"
RESOLUTION_MEDIUM = "MEDIUM"
RESOLUTION_LOW = "LOW"
RESOLUTION_NOT_FOUND = "NOT_FOUND"

RESOLUTION_SOURCE_CANDIDATE = "candidate_db"
RESOLUTION_SOURCE_CONFIG = "config_etf"
RESOLUTION_SOURCE_NASDAQ = "nasdaq"
RESOLUTION_SOURCE_FMP = "fmp_profile"
RESOLUTION_SOURCE_SEC = "sec"
RESOLUTION_SOURCE_UNKNOWN = "unknown"

SECURITY_TYPE_UNRESOLVED = "UNRESOLVED"

CONFIGURED_ETF_SYMBOLS = frozenset(
    SCAN_UNIVERSES.get("Katılım ETF 3", [])
)


class SymbolNotFoundError(ValueError):
    """Raised when a ticker cannot be resolved to a known security."""


@dataclass(frozen=True)
class ResolvedSecurity:
    symbol: str
    company_name: Optional[str]
    exchange: Optional[str]
    security_type: str
    issuer_category: str
    is_etf: bool
    cik: Optional[Any]
    resolution_source: str
    resolution_confidence: str
    is_equity_eligible: bool = False
    classification_warning: Optional[str] = None
    found: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_scan_row(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name or self.symbol,
            "exchange": self.exchange,
            "is_etf": self.is_etf,
            "cik": self.cik,
        }


def normalize_symbol_input(symbol: Optional[str]) -> str:
    return str(symbol or "").strip().upper()


def resolve_symbol(
    symbol: Optional[str],
    *,
    candidate_repo=None,
    fmp_client: Optional[FMPClient] = None,
    sec_lookup: Optional[Mapping[str, Dict[str, Any]]] = None,
    nasdaq_lookup: Optional[Mapping[str, Dict[str, Any]]] = None,
    configured_etf_symbols: Optional[FrozenSet[str]] = None,
) -> ResolvedSecurity:
    normalized = normalize_symbol_input(symbol)
    if not normalized:
        raise SymbolNotFoundError("Sembol boş olamaz.")

    etf_symbols = configured_etf_symbols or CONFIGURED_ETF_SYMBOLS
    sec_lookup = sec_lookup or {}
    nasdaq_lookup = nasdaq_lookup or {}

    if candidate_repo is not None:
        candidate = candidate_repo.get_by_symbol(normalized)
        if candidate:
            is_etf = bool(candidate.get("is_etf")) or _candidate_is_etf(candidate)
            classification = classify_security(
                symbol=normalized,
                company_name=candidate.get("company_name"),
                is_etf=is_etf,
            )
            return ResolvedSecurity(
                symbol=normalized,
                company_name=candidate.get("company_name") or normalized,
                exchange=candidate.get("exchange") or candidate.get("exchange_name"),
                security_type=str(classification["security_type"]),
                issuer_category=str(classification["issuer_category"]),
                is_etf=is_etf,
                cik=candidate.get("cik"),
                resolution_source=RESOLUTION_SOURCE_CANDIDATE,
                resolution_confidence=RESOLUTION_HIGH,
                is_equity_eligible=not is_etf,
            )

    if normalized in etf_symbols:
        return _build_etf_resolution(
            normalized,
            company_name=normalized,
            exchange=None,
            cik=None,
            resolution_source=RESOLUTION_SOURCE_CONFIG,
            resolution_confidence=RESOLUTION_HIGH,
        )

    nasdaq_row = nasdaq_lookup.get(normalized) or {}
    if nasdaq_row.get("is_etf"):
        return _build_etf_resolution(
            normalized,
            company_name=nasdaq_row.get("company_name") or normalized,
            exchange=nasdaq_row.get("exchange"),
            cik=None,
            resolution_source=RESOLUTION_SOURCE_NASDAQ,
            resolution_confidence=RESOLUTION_HIGH,
        )

    profile: Dict[str, Any] = {}
    fmp_error: Optional[FMPError] = None
    if fmp_client is not None:
        try:
            profile = fmp_client.profile(normalized) or {}
        except FMPError as exc:
            fmp_error = exc

    if profile:
        if _profile_is_etf(profile):
            return _build_etf_resolution(
                normalized,
                company_name=(
                    profile.get("companyName")
                    or profile.get("name")
                    or normalized
                ),
                exchange=profile.get("exchange"),
                cik=profile.get("cik"),
                resolution_source=RESOLUTION_SOURCE_FMP,
                resolution_confidence=RESOLUTION_HIGH,
            )
        return _build_equity_resolution(
            normalized,
            company_name=(
                profile.get("companyName")
                or profile.get("name")
                or nasdaq_row.get("company_name")
                or normalized
            ),
            exchange=profile.get("exchange") or nasdaq_row.get("exchange"),
            cik=profile.get("cik") or (sec_lookup.get(normalized) or {}).get("cik"),
            resolution_source=RESOLUTION_SOURCE_FMP,
            resolution_confidence=RESOLUTION_HIGH,
        )

    if nasdaq_row and nasdaq_row.get("is_etf") is False:
        sec_row = sec_lookup.get(normalized) or {}
        return _build_equity_resolution(
            normalized,
            company_name=nasdaq_row.get("company_name") or normalized,
            exchange=nasdaq_row.get("exchange"),
            cik=sec_row.get("cik"),
            resolution_source=RESOLUTION_SOURCE_NASDAQ,
            resolution_confidence=RESOLUTION_HIGH,
        )

    sec_row = sec_lookup.get(normalized) or {}
    if sec_row:
        return _build_unresolved_resolution(
            normalized,
            company_name=sec_row.get("company_name") or normalized,
            exchange=sec_row.get("exchange"),
            cik=sec_row.get("cik"),
            resolution_source=RESOLUTION_SOURCE_SEC,
            fmp_error=fmp_error,
        )

    if fmp_error is not None:
        if fmp_error.error_class == "rate_limit":
            raise fmp_error
        raise SymbolNotFoundError("Sembol bulunamadı.")

    raise SymbolNotFoundError("Sembol bulunamadı.")


def participation_for_symbol(symbol: str) -> tuple[str, int]:
    return PARTICIPATION_DEFAULTS.get(
        normalize_symbol_input(symbol),
        ("Kontrol Et", 60),
    )


def _candidate_is_etf(candidate: Dict[str, Any]) -> bool:
    asset_type = str(candidate.get("asset_type") or "").strip().upper()
    if asset_type in {"ETF", "FON", "FUND"}:
        return True
    security_type = str(candidate.get("security_type") or "").strip().upper()
    return security_type == "ETF"


def _profile_is_etf(profile: Dict[str, Any]) -> bool:
    if profile.get("isEtf") is True or profile.get("isETF") is True:
        return True
    asset_type = str(profile.get("assetType") or profile.get("type") or "").upper()
    return asset_type in {"ETF", "FUND"}


def _build_equity_resolution(
    symbol: str,
    *,
    company_name: Optional[str],
    exchange: Optional[str],
    cik: Optional[Any],
    resolution_source: str,
    resolution_confidence: str,
) -> ResolvedSecurity:
    classification = classify_security(
        symbol=symbol,
        company_name=company_name,
        is_etf=False,
    )
    return ResolvedSecurity(
        symbol=symbol,
        company_name=company_name or symbol,
        exchange=exchange,
        security_type=str(classification["security_type"]),
        issuer_category=str(classification["issuer_category"]),
        is_etf=False,
        cik=cik,
        resolution_source=resolution_source,
        resolution_confidence=resolution_confidence,
        is_equity_eligible=True,
    )


def _build_etf_resolution(
    symbol: str,
    *,
    company_name: Optional[str],
    exchange: Optional[str],
    cik: Optional[Any],
    resolution_source: str,
    resolution_confidence: str,
) -> ResolvedSecurity:
    classification = classify_security(
        symbol=symbol,
        company_name=company_name,
        is_etf=True,
    )
    return ResolvedSecurity(
        symbol=symbol,
        company_name=company_name or symbol,
        exchange=exchange,
        security_type=str(classification["security_type"]),
        issuer_category=str(classification["issuer_category"]),
        is_etf=True,
        cik=cik,
        resolution_source=resolution_source,
        resolution_confidence=resolution_confidence,
        is_equity_eligible=False,
    )


def _build_unresolved_resolution(
    symbol: str,
    *,
    company_name: Optional[str],
    exchange: Optional[str],
    cik: Optional[Any],
    resolution_source: str,
    fmp_error: Optional[FMPError] = None,
) -> ResolvedSecurity:
    warning = None
    if fmp_error is not None and fmp_error.error_class == "rate_limit":
        warning = "FMP rate limit nedeniyle varlık türü doğrulanamadı."
    return ResolvedSecurity(
        symbol=symbol,
        company_name=company_name or symbol,
        exchange=exchange,
        security_type=SECURITY_TYPE_UNRESOLVED,
        issuer_category="UNKNOWN",
        is_etf=False,
        cik=cik,
        resolution_source=resolution_source,
        resolution_confidence=RESOLUTION_LOW,
        is_equity_eligible=False,
        classification_warning=warning,
    )
