"""Automatic Turkish participation-fund universe discovery.

Official KAP/TEFAS identity only. No ticker allowlist. No fuzzy name matching.
A title containing Katılım is discovery evidence, not Participation=Uygun.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from services.fund_product_contract import PDR_SUBJECT, PDR_SUBJECT_OID, PROVIDER_KAP_FUND, PROVIDER_TEFAS
from services.official_kap_pdr import _fold, parse_tr_number
from services.official_tefas import normalize_fund_code
from services.turkiye_fund_universe_contract import (
    EVIDENCE_KAP_IDENTITY,
    EVIDENCE_KAP_TITLE_KATILIM,
    EVIDENCE_KAP_UMBRELLA_KATILIM,
    EVIDENCE_TEFAS_CATEGORY_KATILIM,
    EVIDENCE_TEFAS_IDENTITY,
    INSTRUMENT_FUND,
    MARKET_TR,
    TEFAS_STATUS_ACTIVE,
    TEFAS_STATUS_INACTIVE,
    TEFAS_STATUS_UNPROVEN,
    TurkiyeFundUniverseIdentity,
)

KAP_PDR_DISCOVERY_URL = "https://www.kap.org.tr/tr/api/disclosure/funds/byCriteria"
TEFAS_SNAPSHOT_URL = "https://www.tefas.gov.tr/api/funds/fonBilgiGetir"
UMBRELLA_KATILIM = "katilim semsiye fonu"
TITLE_KATILIM = "katilim"
TEFAS_CATEGORY_KATILIM = "katilim fonu"

DISCOVERY_CASH_LIKE = "cash_like"
DISCOVERY_EQUITY = "equity"
DISCOVERY_SUKUK = "sukuk"
DISCOVERY_PRECIOUS_METALS = "precious_metals"
DISCOVERY_REAL_ESTATE = "real_estate"
DISCOVERY_MULTI_ASSET = "multi_asset"
DISCOVERY_OTHER = "other"


def _float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    parsed = parse_tr_number(value)
    if parsed is not None:
        return parsed
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def official_title_has_katilim(title: Any) -> bool:
    return TITLE_KATILIM in _fold(title)


def official_umbrella_is_katilim(umbrella_type: Any) -> bool:
    folded = _fold(umbrella_type)
    return bool(folded) and (UMBRELLA_KATILIM in folded or folded == "katilim")


def official_tefas_category_is_katilim(category: Any) -> bool:
    return TEFAS_CATEGORY_KATILIM in _fold(category)


def discovery_category_from_official_title(title: Any) -> str:
    """Peer-sample hint from official KAP title. Not Participation and not FI profile."""
    folded = _fold(title)
    if "para piyasa" in folded:
        return DISCOVERY_CASH_LIKE
    if "hisse" in folded:
        return DISCOVERY_EQUITY
    if "kira sertifika" in folded or "sukuk" in folded:
        return DISCOVERY_SUKUK
    if any(token in folded for token in ("altin", "kiymetli maden", "gumus", "gold")):
        return DISCOVERY_PRECIOUS_METALS
    if "gayrimenkul" in folded:
        return DISCOVERY_REAL_ESTATE
    if any(token in folded for token in ("fon sepeti fonu", "degisken fon", "karma fon")):
        return DISCOVERY_MULTI_ASSET
    return DISCOVERY_OTHER


def manager_prefix_from_official_title(title: Any) -> str:
    folded = _fold(title)
    marker = " portfoy"
    if marker in folded:
        return folded.split(marker, 1)[0].strip()
    return folded.split(" ", 1)[0] if folded else ""


def _latest_by_fund_code(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        code = normalize_fund_code(row.get("fundCode"))
        if not code:
            continue
        subject = str(row.get("subject") or PDR_SUBJECT).strip()
        if subject and subject != PDR_SUBJECT:
            continue
        key = (
            int(row.get("year") or 0),
            int(row.get("period") or 0),
            int(row.get("disclosureIndex") or 0),
        )
        prev = latest.get(code)
        if prev is None:
            latest[code] = row
            continue
        prev_key = (
            int(prev.get("year") or 0),
            int(prev.get("period") or 0),
            int(prev.get("disclosureIndex") or 0),
        )
        if key > prev_key:
            latest[code] = row
    return latest


def _tefas_status(snapshot: Optional[Mapping[str, Any]]) -> str:
    if snapshot is None:
        return TEFAS_STATUS_UNPROVEN
    if not snapshot.get("tefas_present", True):
        return TEFAS_STATUS_INACTIVE
    price = snapshot.get("sonFiyat")
    code = snapshot.get("fonKodu") or snapshot.get("fonkod")
    if price in (None, "") and not snapshot.get("fonUnvan"):
        return TEFAS_STATUS_INACTIVE
    if code or price not in (None, ""):
        return TEFAS_STATUS_ACTIVE
    return TEFAS_STATUS_INACTIVE


def discover_turkiye_participation_universe(
    rows: Sequence[Mapping[str, Any]],
    *,
    tefas_snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> tuple[TurkiyeFundUniverseIdentity, ...]:
    """Deduplicate by canonical fund code. No fuzzy names. No ticker allowlist."""
    snapshots = {normalize_fund_code(key): dict(value) for key, value in dict(tefas_snapshots or {}).items()}
    identities: list[TurkiyeFundUniverseIdentity] = []
    for code, row in sorted(_latest_by_fund_code(rows).items()):
        title = str(row.get("kapTitle") or row.get("official_name") or "") or None
        umbrella = str(row.get("umbrellaType") or row.get("umbrella_type") or "") or None
        snap = snapshots.get(code)
        tefas_category = None
        if snap:
            tefas_category = str(snap.get("fonKategori") or "") or None
        evidence: list[str] = [EVIDENCE_KAP_IDENTITY]
        if official_title_has_katilim(title):
            evidence.append(EVIDENCE_KAP_TITLE_KATILIM)
        if official_umbrella_is_katilim(umbrella):
            evidence.append(EVIDENCE_KAP_UMBRELLA_KATILIM)
        if official_tefas_category_is_katilim(tefas_category):
            evidence.append(EVIDENCE_TEFAS_CATEGORY_KATILIM)
        if snap and _tefas_status(snap) == TEFAS_STATUS_ACTIVE:
            evidence.append(EVIDENCE_TEFAS_IDENTITY)
        if EVIDENCE_KAP_TITLE_KATILIM not in evidence and EVIDENCE_KAP_UMBRELLA_KATILIM not in evidence:
            if EVIDENCE_TEFAS_CATEGORY_KATILIM not in evidence:
                continue
        status = _tefas_status(snap) if snap is not None else TEFAS_STATUS_UNPROVEN
        if snap is not None and status == TEFAS_STATUS_UNPROVEN:
            status = TEFAS_STATUS_INACTIVE
        provenance = [PROVIDER_KAP_FUND, KAP_PDR_DISCOVERY_URL, f"subject_oid:{PDR_SUBJECT_OID}"]
        if snap is not None:
            provenance.extend([PROVIDER_TEFAS, TEFAS_SNAPSHOT_URL])
        identities.append(
            TurkiyeFundUniverseIdentity(
                fund_code=code,
                fund_name=title or (str(snap.get("fonUnvan") or "") if snap else None) or None,
                isin=str(row.get("isin") or "") or None,
                founder=str(row.get("founder") or "") or None,
                instrument=INSTRUMENT_FUND,
                market=MARKET_TR,
                currency=str(row.get("currency") or "") or None,
                umbrella_type=umbrella,
                tefas_status=status,
                tefas_category=tefas_category,
                source_provenance=tuple(provenance),
                discovery_evidence=tuple(dict.fromkeys(evidence)),
                kap_publish_date=str(row.get("publishDate") or "") or None,
                pdr_year=_int(row.get("year")),
                pdr_period=_int(row.get("period")),
                kap_disclosure_index=_int(row.get("disclosureIndex")),
                unit_price=_float((snap or {}).get("sonFiyat")),
                price_date=str((snap or {}).get("fiyatTarih") or "") or None,
                fund_total_value=_float((snap or {}).get("portBuyukluk")),
                investor_count=_int((snap or {}).get("yatirimciSayi")),
            )
        )
    return tuple(identities)


def select_representative_sample(
    identities: Sequence[TurkiyeFundUniverseIdentity],
    *,
    extra_per_category: int = 1,
    include_if_discovered: Sequence[str] = (),
) -> tuple[str, ...]:
    """Deterministic multi-manager sample FROM discovery. Not a hardcoded universe."""
    by_code = {row.fund_code: row for row in identities}
    selected: list[str] = [
        code for code in include_if_discovered if normalize_fund_code(code) in by_code
    ]
    used_managers = {manager_prefix_from_official_title(by_code[code].fund_name) for code in selected}
    buckets: dict[str, list[TurkiyeFundUniverseIdentity]] = {}
    for row in identities:
        if row.fund_code in selected:
            continue
        buckets.setdefault(discovery_category_from_official_title(row.fund_name), []).append(row)
    for category in (
        DISCOVERY_CASH_LIKE,
        DISCOVERY_EQUITY,
        DISCOVERY_SUKUK,
        DISCOVERY_PRECIOUS_METALS,
        DISCOVERY_REAL_ESTATE,
        DISCOVERY_OTHER,
    ):
        taken = 0
        for row in sorted(buckets.get(category) or (), key=lambda item: item.fund_code):
            if taken >= extra_per_category:
                break
            manager = manager_prefix_from_official_title(row.fund_name)
            if manager and manager in used_managers and taken == 0 and extra_per_category <= 1:
                continue
            selected.append(row.fund_code)
            used_managers.add(manager)
            taken += 1
    if len(selected) <= 3:
        extras = [row.fund_code for row in identities if row.fund_code not in selected]
        selected.extend(extras[: max(0, 4 - len(selected))])
    return tuple(dict.fromkeys(selected))
