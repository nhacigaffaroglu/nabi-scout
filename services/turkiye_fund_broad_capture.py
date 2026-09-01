"""Broad official KAP/TEFAS evidence capture for the discovered universe.

Per-fund isolation, incremental cache, polite HTTP. Research capture only.
Does not persist production Participation/FI snapshots, 8E, or New Money.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from services.fund_product_contract import IDENTITY_RESOLVED, IDENTITY_UNRESOLVED, PILOT_TEFAS_FUND_CODES
from services.official_kap_fund import (
    OZET_LABEL_FOUNDER,
    OZET_LABEL_UMBRELLA_NAME,
    OZET_LABEL_UMBRELLA_TYPE,
    parse_kap_ybf_text,
)
from services.official_kap_pdr import (
    asset_group_weights,
    discover_latest_pdr,
    parse_kap_pdr_text,
    report_period_label,
)
from services.official_tefas import normalize_fund_code
from services.turkiye_fund_evidence_extract import (
    extract_governance_excerpts,
    extract_mandate_excerpts,
    extract_purification_excerpts,
)
from services.turkiye_fund_kap_rsc import (
    kap_file_url,
    parse_kap_bildirim_rsc,
    parse_kap_genel_rsc,
    parse_kap_ozet_rsc,
)
from services.turkiye_fund_kap_slug import kap_genel_url, kap_official_slug, kap_ozet_url
from services.turkiye_fund_pdr_window import latest_applicable_pdr_period, pdr_row_is_applicable
from services.turkiye_fund_pdf_text import sha256_hex, try_extract_pdf_text, unwrap_kap_file_bytes
from services.turkiye_fund_source_capture import (
    CACHE_DIR,
    KAP_MIN_GAP_SEC,
    TEFAS_RETURNS_URL,
    TEFAS_SNAPSHOT_URL,
    CaptureRunStats,
    OfficialCaptureSession,
    capture_kap_fund_directory,
    cache_identity,
    load_or_store,
    read_cached_payload,
    read_evidence_pack,
    write_cached_pdr_text,
    write_evidence_pack,
)
from services.turkiye_fund_tefas_history import capture_tefas_history
from services.turkiye_fund_text_recovery import recover_official_document_text
from services.turkiye_fund_universe_contract import TEFAS_STATUS_ACTIVE, TurkiyeFundUniverseIdentity

EVIDENCE_RECOVERY_VERSION = 9
ACCEPTED_PACK_VERSIONS = frozenset({8, 9})

KAP_BILDIRIM = "https://www.kap.org.tr/tr/Bildirim/{index}"


def _as_of(value: Optional[date]) -> date:
    return value or date(2026, 8, 31)


def pdr_parser_quality(file) -> dict[str, Any]:
    if file is None:
        return {
            "row_count": 0,
            "reported_weight": None,
            "known_weight": None,
            "unknown_weight": None,
            "reconciliation": None,
            "issuer_coverage": 0.0,
            "maturity_coverage": 0.0,
            "currency_coverage": 0.0,
            "asset_groups": {},
            "renormalized": False,
        }
    holdings = tuple(file.holdings or ())
    total = len(holdings) or 1
    issuer_n = sum(1 for row in holdings if row.issuer_raw)
    maturity_n = sum(1 for row in holdings if row.maturity_date)
    currency_n = sum(1 for row in holdings if row.currency)
    weights = file.weights
    return {
        "row_count": len(holdings),
        "reported_weight": getattr(weights, "reported_weight_sum", None),
        "known_weight": getattr(weights, "known_weight", None),
        "unknown_weight": getattr(weights, "unknown_weight", None),
        "reconciliation": bool(getattr(weights, "weight_reconciled", False)),
        "issuer_coverage": round(issuer_n / total, 4),
        "maturity_coverage": round(maturity_n / total, 4),
        "currency_coverage": round(currency_n / total, 4),
        "isin_coverage": round(sum(1 for row in holdings if row.isin) / total, 4),
        "asset_groups": asset_group_weights(file),
        "renormalized": bool(getattr(weights, "renormalized", False)),
    }


def _fetch_pdf_text(
    session: OfficialCaptureSession,
    file_oid: str,
    *,
    referer: str = "",
    published_at: str = "",
) -> tuple[Optional[str], Optional[str], bool]:
    identity = cache_identity(kind="kap_pdf_text_v6", key=file_oid, published_at=published_at)
    cached = read_cached_payload("kap_pdf_text_v6", identity)
    if cached and cached.get("text"):
        session.stats.cache_hits += 1
        session.stats.unchanged_documents += 1
        return str(cached["text"]), str(cached.get("sha256") or "") or None, True
    url = kap_file_url(file_oid)
    raw = session.http_get_bytes(url, accept="application/pdf,application/octet-stream", referer=referer)
    pdf = unwrap_kap_file_bytes(raw)
    text, error = try_extract_pdf_text(pdf)
    if text is None:
        return None, error, False
    digest = sha256_hex(pdf)
    load_or_store(
        kind="kap_pdf_text_v6",
        key=file_oid,
        published_at=published_at,
        fetcher=lambda: {"text": text, "sha256": digest, "bytes": len(pdf)},
        force=True,
        stats=session.stats,
    )
    return text, digest, False


def capture_tefas_snapshot(session: OfficialCaptureSession, fund_code: str) -> dict[str, Any]:
    code = normalize_fund_code(fund_code)

    def _fetch() -> dict[str, Any]:
        payload = session.http_json(
            TEFAS_SNAPSHOT_URL,
            {"fonKodu": code},
            referer="https://www.tefas.gov.tr/",
        )
        rows = list(payload.get("resultList") or [])
        if not rows:
            return {"fonKodu": code, "tefas_present": False}
        return {**dict(rows[0]), "tefas_present": True}

    payload, hit = load_or_store(kind="tefas_snapshot", key=code, fetcher=_fetch, stats=session.stats)
    payload["cache_hit"] = hit
    return payload


def capture_tefas_returns(session: OfficialCaptureSession, fund_code: str) -> Optional[dict[str, Any]]:
    code = normalize_fund_code(fund_code)

    def _fetch() -> dict[str, Any]:
        payload = session.http_json(
            TEFAS_RETURNS_URL,
            {"fonKodu": code},
            referer="https://www.tefas.gov.tr/",
        )
        rows = list(payload.get("resultList") or [])
        if not rows:
            return {"fonKodu": code, "available": False, "error": payload.get("errorMessage")}
        return {**dict(rows[0]), "available": True}

    try:
        payload, _hit = load_or_store(kind="tefas_returns", key=code, fetcher=_fetch, stats=session.stats)
    except Exception as exc:  # noqa: BLE001 — per-fund isolation
        return {"fonKodu": code, "available": False, "error": str(exc)[:240]}
    return dict(payload)


def _attach_tefas(
    pack: dict[str, Any],
    *,
    session: OfficialCaptureSession,
    code: str,
    day: date,
    fetch_prices: bool,
    reasons: list[str],
    errors: list[str],
) -> None:
    """Official TEFAS snapshot/history does not depend on KAP özet success."""
    try:
        snap = capture_tefas_snapshot(session, code)
        pack["tefas_snapshot"] = {k: v for k, v in snap.items() if k != "cache_hit"}
        if not snap.get("tefas_present"):
            reasons.append("TEFAS_INACTIVE")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"TEFAS_SNAPSHOT:{exc}"[:240])
        reasons.append("SOURCE_ERROR")
    returns = capture_tefas_returns(session, code)
    pack["tefas_returns"] = returns
    if fetch_prices:
        prices = capture_tefas_history(session, code, as_of=day)
        pack["tefas_prices"] = {
            "available": bool(prices and prices.get("available")),
            "error": (prices or {}).get("error"),
            "row_count": int((prices or {}).get("row_count") or len(list((prices or {}).get("rows") or []))),
            "periyod": (prices or {}).get("periyod"),
            "latest_date": (prices or {}).get("latest_date"),
            "pilot_frozen": bool((prices or {}).get("pilot_frozen")),
        }
        if not (prices and prices.get("available")):
            reasons.append("HISTORY_INSUFFICIENT")
            pack["tefas_price_rows"] = []
        else:
            pack["tefas_price_rows"] = list(prices.get("rows") or [])


def capture_one_fund(
    identity: TurkiyeFundUniverseIdentity,
    *,
    session: OfficialCaptureSession,
    catalog_rows: Sequence[Mapping[str, Any]],
    as_of: Optional[date] = None,
    fetch_prices: bool = True,
    allow_ocr: bool = False,
    kap_directory: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Capture official evidence for one fund. Failures stay on this fund."""
    day = _as_of(as_of)
    code = identity.fund_code
    if code in PILOT_TEFAS_FUND_CODES:
        pack = {
            "fund_code": code,
            "source_as_of": day.isoformat(),
            "calculated_at": day.isoformat(),
            "official_name": identity.fund_name,
            "identity_status": IDENTITY_RESOLVED,
            "tefas_status": identity.tefas_status,
            "errors": [],
            "review_reasons": [],
            "production_persist": False,
            "evidence_recovery_version": EVIDENCE_RECOVERY_VERSION,
            "pilot_frozen": True,
        }
        _write_pack(code, pack)
        return pack
    errors: list[str] = []
    reasons: list[str] = []
    pack: dict[str, Any] = {
        "fund_code": code,
        "source_as_of": day.isoformat(),
        "calculated_at": day.isoformat(),
        "official_name": identity.fund_name,
        "kap_disclosure_index": identity.kap_disclosure_index,
        "pdr_year": identity.pdr_year,
        "pdr_period": identity.pdr_period,
        "tefas_status": identity.tefas_status,
        "errors": errors,
        "review_reasons": reasons,
        "production_persist": False,
        "evidence_recovery_version": EVIDENCE_RECOVERY_VERSION,
    }
    if identity.tefas_status != TEFAS_STATUS_ACTIVE:
        reasons.append("TEFAS_INACTIVE")
        pack["identity_status"] = IDENTITY_UNRESOLVED
        _write_pack(code, pack)
        return pack

    directory_row = dict((kap_directory or {}).get(code) or {})
    directory_name = str(directory_row.get("fund_name") or "").strip()
    directory_founder = str(directory_row.get("founder") or "").strip()
    title = directory_name or identity.fund_name or ""
    slug = str(directory_row.get("slug") or "").strip() or kap_official_slug(code, title)
    if directory_row:
        pack["kap_directory_identity"] = {
            "fund_code": code,
            "fund_name": directory_name or None,
            "founder": directory_founder or None,
            "slug": slug or None,
        }
        if directory_name and directory_name != (identity.fund_name or ""):
            pack["identity_name_updated"] = True
    pack["kap_slug"] = slug or None
    pack["ozet_url"] = kap_ozet_url(code, title) or None
    pack["genel_url"] = kap_genel_url(code, title) or None
    if not slug:
        reasons.append("IDENTITY_UNRESOLVED")
        pack["identity_status"] = IDENTITY_UNRESOLVED
        _attach_tefas(
            pack, session=session, code=code, day=day, fetch_prices=fetch_prices, reasons=reasons, errors=errors
        )
        pack["review_reasons"] = list(dict.fromkeys(reasons))
        pack["errors"] = list(dict.fromkeys(errors))
        _write_pack(code, pack)
        return pack

    ozet = {}
    try:
        ozet_text, ozet_hit = load_or_store(
            kind="kap_ozet_rsc",
            key=slug,
            fetcher=lambda: {"text": session.kap_rsc(pack["ozet_url"])},
            stats=session.stats,
        )
        ozet = parse_kap_ozet_rsc(str(ozet_text.get("text") or ""))
        pack["ozet_cache_hit"] = ozet_hit
    except Exception as exc:  # noqa: BLE001
        # Özet is useful for document metadata but must not be a single point
        # of failure for identity. Continue to the independent KAP Genel page;
        # a successful exact-slug Genel parse can recover identity while this
        # source error remains retryable for missing documents.
        errors.append(f"KAP_OZET:{exc}"[:240])
        reasons.append("SOURCE_ERROR")

    if ozet.get("fund_code") and ozet["fund_code"] != code:
        reasons.append("IDENTITY_UNRESOLVED")
        pack["identity_status"] = IDENTITY_UNRESOLVED
        pack["ozet"] = {"fund_code": ozet.get("fund_code")}
        _attach_tefas(
            pack, session=session, code=code, day=day, fetch_prices=fetch_prices, reasons=reasons, errors=errors
        )
        pack["review_reasons"] = list(dict.fromkeys(reasons))
        pack["errors"] = list(dict.fromkeys(errors))
        _write_pack(code, pack)
        return pack

    directory_resolved = bool(directory_row and directory_name)
    pack["identity_status"] = (
        IDENTITY_RESOLVED if ozet.get("resolved") or directory_resolved else IDENTITY_UNRESOLVED
    )
    if directory_resolved and not ozet.get("resolved"):
        pack["identity_source"] = "KAP_FUND_DIRECTORY"
    pack["founder"] = ozet.get("founder") or directory_founder or identity.founder
    pack["official_name"] = ozet.get("official_name") or directory_name or identity.fund_name
    pack["umbrella_type"] = (ozet.get("ozet_fields") or {}).get("Fonun Bağlı Olduğu Şemsiye Fonun Türü")
    pack["umbrella_name"] = (ozet.get("ozet_fields") or {}).get("Fonun Bağlı Olduğu Şemsiye Fonun Ünvanı")
    pack["fund_type"] = ozet.get("fund_type")
    pack["ozet_fields"] = ozet.get("ozet_fields") or {}
    pack["documents"] = ozet.get("documents") or {}
    if pack["identity_status"] != IDENTITY_RESOLVED:
        reasons.append("IDENTITY_UNRESOLVED")

    try:
        genel_text, _hit = load_or_store(
            kind="kap_genel_rsc",
            key=slug,
            fetcher=lambda: {"text": session.kap_rsc(pack["genel_url"])},
            stats=session.stats,
        )
        genel = parse_kap_genel_rsc(str(genel_text.get("text") or ""))
        pack["isin"] = genel.get("isin")
        pack["genel_items"] = {
            key: value
            for key, value in dict(genel.get("items") or {}).items()
            if key
            in {
                "kpy81_acc1_ISIN",
                "kpy81_acc1_kurucu_unvan",
                "kpy81_acc1_fon_sem_tur",
                "kpy81_acc1_fon_sem_unvan",
            }
        }
        _fill_ozet_from_genel(pack)
        if pack.get("identity_status") != IDENTITY_RESOLVED and _genel_identity_evidence(genel):
            pack["identity_status"] = IDENTITY_RESOLVED
            pack["identity_source"] = "KAP_GENEL_EXACT_SLUG"
            reasons[:] = [reason for reason in reasons if reason != "IDENTITY_UNRESOLVED"]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"KAP_GENEL:{exc}"[:240])
        reasons.append("SOURCE_ERROR")

    ybf_oid = ozet.get("ybf_file_oid")
    izahname_oid = ozet.get("izahname_file_oid")
    ybf_doc = (ozet.get("documents") or {}).get("BILGI_FORMU") or {}
    izah_doc = (ozet.get("documents") or {}).get("IZAHNAME") or {}
    ybf_text = None
    izahname_text = None
    ybf_recovery = None
    izah_recovery = None
    if ybf_oid:
        last_resort = bool(allow_ocr and pack.get("identity_status") == IDENTITY_RESOLVED)
        ybf_recovery = recover_official_document_text(
            session,
            file_oid=str(ybf_oid),
            disclosure_index=ybf_doc.get("disclosure_index"),
            document_type="YBF",
            published_at=str(pack.get("source_as_of") or ""),
            referer=pack["ozet_url"] or "",
            allow_ocr=last_resort,
        )
        ybf_text = ybf_recovery.get("text") if ybf_recovery.get("text_available") else None
        pack["ybf_url"] = kap_file_url(ybf_oid)
        pack["ybf_sha256"] = ybf_recovery.get("text_hash")
        pack["ybf_recovery"] = {k: v for k, v in ybf_recovery.items() if k != "text"}
        if ybf_text is None:
            errors.append(f"YBF_TEXT:{ybf_recovery.get('pdf_error') or ybf_recovery.get('ocr_error') or 'unavailable'}"[:240])
            reasons.append("TEXT_LAYER_UNAVAILABLE")
    else:
        reasons.append("YBF_MISSING")
    if izahname_oid:
        last_resort = bool(allow_ocr and pack.get("identity_status") == IDENTITY_RESOLVED)
        izah_recovery = recover_official_document_text(
            session,
            file_oid=str(izahname_oid),
            disclosure_index=izah_doc.get("disclosure_index"),
            document_type="IZAHNAME",
            published_at=str(pack.get("source_as_of") or ""),
            referer=pack["ozet_url"] or "",
            allow_ocr=last_resort,
        )
        izahname_text = izah_recovery.get("text") if izah_recovery.get("text_available") else None
        pack["izahname_url"] = kap_file_url(izahname_oid)
        pack["izahname_sha256"] = izah_recovery.get("text_hash")
        pack["izahname_recovery"] = {k: v for k, v in izah_recovery.items() if k != "text"}

    if ybf_text:
        pack["ybf_facts"] = parse_kap_ybf_text(ybf_text)
        pack["ybf"] = {
            "official_name": pack.get("official_name"),
            "isin": pack.get("isin") or (pack["ybf_facts"] or {}).get("isin"),
            "status_sentence": next(iter(extract_mandate_excerpts(ybf_text)), None),
            "strategy": _strategy_paragraph(ybf_text),
            "currency_sentence": next(
                (line for line in ybf_text.splitlines() if "para birimi" in line.casefold()),
                None,
            ),
            "management_fee_annual_pct": (pack["ybf_facts"] or {}).get("management_fee_annual_pct"),
            "text_origin": (ybf_recovery or {}).get("text_origin"),
        }
        if (ybf_recovery or {}).get("text_origin") != "OCR_FROM_OFFICIAL_DOCUMENT":
            pack["ybf_text"] = ybf_text
    elif ybf_oid:
        reasons.append("YBF_MISSING")

    pack["mandate_excerpts"] = list(extract_mandate_excerpts(ybf_text or "", izahname_text or ""))
    pack["governance_excerpts"] = list(extract_governance_excerpts(izahname_text or "", ybf_text or ""))
    pack["purification_excerpts"] = list(extract_purification_excerpts(izahname_text or "", ybf_text or ""))
    if not pack["governance_excerpts"]:
        reasons.append("GOVERNANCE_EVIDENCE_MISSING")

    pdr_row = _latest_applicable_row(catalog_rows, code, day)
    year, month = latest_applicable_pdr_period(day)
    if pdr_row is None:
        reasons.append("PDR_MISSING")
        _ = year, month
    else:
        index = int(pdr_row.get("disclosureIndex") or 0)
        period = report_period_label(pdr_row.get("year"), pdr_row.get("period"))
        pack["pdr_publish_date"] = str(pdr_row.get("publishDate") or "") or None
        pack["pdr_period"] = period
        pack["published_at"] = pack["pdr_publish_date"]
        pack["effective_at"] = period
        try:
            bildirim, _hit = load_or_store(
                kind="kap_bildirim_rsc",
                key=str(index),
                published_at=str(pdr_row.get("publishDate") or ""),
                fetcher=lambda: {"text": session.kap_rsc(KAP_BILDIRIM.format(index=index))},
                stats=session.stats,
            )
            parsed = parse_kap_bildirim_rsc(str(bildirim.get("text") or ""))
            pdr_oid = parsed.get("file_oid")
            pack["pdr_file_oid"] = pdr_oid
            pack["pdr_file_name"] = parsed.get("file_name")
            pack["pdr_source_url"] = KAP_BILDIRIM.format(index=index)
            if not pdr_oid:
                reasons.append("PDR_MISSING")
            else:
                pdr_text, pdr_sha, _hit = _safe_pdf(
                    session,
                    pdr_oid,
                    referer=pack["pdr_source_url"],
                    errors=errors,
                    reasons=reasons,
                    reason_on_fail="PDR_PARSE_INCOMPLETE",
                )
                pack["pdr_sha256"] = pdr_sha
                if pdr_text:
                    write_cached_pdr_text(code, period or "unknown", pdr_text)
                    try:
                        parsed_pdr = parse_kap_pdr_text(
                            pdr_text,
                            fund_code=code,
                            report_period=period,
                            source_notification_id=str(index),
                            source_attachment=str(parsed.get("file_name") or ""),
                            source_url=pack["pdr_source_url"],
                        )
                        quality = pdr_parser_quality(parsed_pdr)
                        pack["pdr_quality"] = quality
                        if not parsed_pdr.holdings:
                            reasons.append("PDR_PARSE_INCOMPLETE")
                        if quality.get("reconciliation") is False:
                            reasons.append("PDR_RECONCILIATION_FAILED")
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"PDR_PARSE:{exc}"[:240])
                        reasons.append("PDR_PARSE_INCOMPLETE")
                else:
                    reasons.append("PDR_PARSE_INCOMPLETE")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"KAP_PDR:{exc}"[:240])
            reasons.append("SOURCE_ERROR")
            reasons.append("PDR_MISSING")

    _attach_tefas(
        pack, session=session, code=code, day=day, fetch_prices=fetch_prices, reasons=reasons, errors=errors
    )

    pack["review_reasons"] = list(dict.fromkeys(reasons))
    pack["errors"] = list(dict.fromkeys(errors))
    _write_pack(code, pack)
    return pack


def _stamp_checkpoint(pack: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    reasons = tuple(pack.get("review_reasons") or ())
    ybf = dict(pack.get("ybf_recovery") or {})
    izah = dict(pack.get("izahname_recovery") or {})
    quality = dict(pack.get("pdr_quality") or {})
    identity_ok = pack.get("identity_status") == IDENTITY_RESOLVED
    pack["capture_checkpoint"] = {
        "identity_status": pack.get("identity_status"),
        "documents_status": "PRESENT" if pack.get("documents") or pack.get("ybf_url") else "MISSING",
        "YBF_status": ybf.get("source_layer") or ("MISSING" if "YBF_MISSING" in reasons else None),
        "izahname_status": izah.get("source_layer"),
        "PDR_status": (
            "READY"
            if quality.get("row_count")
            else ("PARSE_INCOMPLETE" if "PDR_PARSE_INCOMPLETE" in reasons else ("MISSING" if "PDR_MISSING" in reasons else None))
        ),
        "last_attempt": now,
        "last_success": now if identity_ok and "SOURCE_ERROR" not in reasons else None,
        "source_identity": pack.get("kap_slug") or pack.get("fund_code"),
        "file_oid": pack.get("pdr_file_oid") or ((pack.get("documents") or {}).get("BILGI_FORMU") or {}).get("file_oid"),
        "published_at": pack.get("published_at") or pack.get("source_as_of"),
        "content_hash": pack.get("ybf_sha256") or pack.get("pdr_sha256"),
        "document_type": "YBF" if pack.get("ybf_url") else None,
        "error_type": next((item for item in reasons if item in {"SOURCE_ERROR", "IDENTITY_UNRESOLVED"}), None),
        "retry_eligible": "SOURCE_ERROR" in reasons or not identity_ok,
    }


def _write_pack(code: str, pack: dict[str, Any]):
    _stamp_checkpoint(pack)
    return write_evidence_pack(code, pack)


def _safe_pdf(
    session: OfficialCaptureSession,
    file_oid: str,
    *,
    referer: str,
    errors: list[str],
    reasons: list[str],
    reason_on_fail: str = "SOURCE_ERROR",
) -> tuple[Optional[str], Optional[str], bool]:
    try:
        return _fetch_pdf_text(session, file_oid, referer=referer)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"KAP_FILE:{file_oid}:{exc}"[:240])
        reasons.append(reason_on_fail)
        return None, None, False



def _genel_identity_evidence(genel: Mapping[str, Any]) -> bool:
    """Exact KAP fund slug + substantive Genel fields is sufficient identity evidence.

    This is intentionally narrow: an empty/partial page does not resolve identity.
    The slug itself is deterministically built from the official fund code/title.
    """
    if not bool(genel.get("resolved")):
        return False
    items = dict(genel.get("items") or {})
    return bool(
        str(genel.get("isin") or "").strip()
        or str(items.get("kpy81_acc1_kurucu_unvan") or "").strip()
        or str(items.get("kpy81_acc1_fon_sem_unvan") or "").strip()
    )

def _fill_ozet_from_genel(pack: dict[str, Any]) -> None:
    """Prefer KAP genel item values when özet RSC captured the label as the value."""
    mapping = {
        "kpy81_acc1_kurucu_unvan": OZET_LABEL_FOUNDER,
        "kpy81_acc1_fon_sem_unvan": OZET_LABEL_UMBRELLA_NAME,
        "kpy81_acc1_fon_sem_tur": OZET_LABEL_UMBRELLA_TYPE,
    }
    fields = dict(pack.get("ozet_fields") or {})
    items = dict(pack.get("genel_items") or {})
    for key, label in mapping.items():
        value = str(items.get(key) or "").strip()
        current = str(fields.get(label) or "").strip()
        if value and (not current or current == label):
            fields[label] = value
    pack["ozet_fields"] = fields
    if fields.get(OZET_LABEL_UMBRELLA_TYPE):
        pack["umbrella_type"] = fields.get(OZET_LABEL_UMBRELLA_TYPE)
    if fields.get(OZET_LABEL_UMBRELLA_NAME):
        pack["umbrella_name"] = fields.get(OZET_LABEL_UMBRELLA_NAME)
    pack["founder"] = pack.get("founder") or fields.get(OZET_LABEL_FOUNDER)


def _strategy_paragraph(text: str) -> Optional[str]:
    for paragraph in str(text or "").split("\n\n"):
        folded = paragraph.casefold()
        if "yatırılır" in folded or "portföy" in folded and "en az" in folded:
            compact = " ".join(paragraph.split())
            if len(compact) >= 40:
                return compact[:1200]
    lines = [line.strip() for line in str(text or "").splitlines() if len(line.strip()) > 40]
    return " ".join(lines[:4])[:1200] if lines else None


def _latest_applicable_row(
    rows: Sequence[Mapping[str, Any]],
    fund_code: str,
    as_of: date,
) -> Optional[dict[str, Any]]:
    discovery = discover_latest_pdr(rows, fund_code, as_of=as_of)
    if not discovery.resolved:
        return None
    code = normalize_fund_code(fund_code)
    matches = [
        dict(row)
        for row in rows
        if normalize_fund_code(row.get("fundCode")) == code and pdr_row_is_applicable(row, as_of)
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda row: (
            int(row.get("year") or 0),
            int(row.get("period") or 0),
            int(row.get("disclosureIndex") or 0),
        ),
    )


def capture_universe(
    identities: Sequence[TurkiyeFundUniverseIdentity],
    *,
    catalog_rows: Sequence[Mapping[str, Any]],
    live: bool = False,
    as_of: Optional[date] = None,
    session: Optional[OfficialCaptureSession] = None,
    resume: bool = True,
    only_fund_codes: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
    fetch_prices: bool = True,
    allow_ocr: bool = True,
    on_fund: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> tuple[dict[str, dict[str, Any]], CaptureRunStats]:
    active = [row for row in identities if row.tefas_status == TEFAS_STATUS_ACTIVE]
    if only_fund_codes is not None:
        requested = {normalize_fund_code(code) for code in only_fund_codes if normalize_fund_code(code)}
        active = [row for row in active if row.fund_code in requested]
    if limit is not None:
        active = active[: int(limit)]
    sess = session or OfficialCaptureSession(live=live, min_gap_sec=KAP_MIN_GAP_SEC if live else 0.0)
    directory: dict[str, dict[str, Any]] = {}
    if live or sess.live:
        sess.ensure_kap_session()
        try:
            directory = capture_kap_fund_directory(sess)
        except Exception:
            # Directory is an optimization / identity fallback only. Per-fund
            # KAP evidence remains authoritative and fail-closed if this page
            # is temporarily unavailable or changes shape.
            directory = {}
    started = time.monotonic()
    packs: dict[str, dict[str, Any]] = {}
    for identity in active:
        sess.stats.funds_attempted += 1
        if resume:
            existing = read_evidence_pack(identity.fund_code)
            if existing and _pack_is_reusable(existing, identity):
                sess.stats.cache_hits += 1
                sess.stats.unchanged_documents += 1
                sess.stats.skipped_unchanged += 1
                sess.stats.funds_ok += 1
                packs[identity.fund_code] = existing
                if on_fund:
                    on_fund(identity.fund_code, existing)
                continue
        try:
            pack = capture_one_fund(
                identity,
                session=sess,
                catalog_rows=catalog_rows,
                as_of=as_of,
                fetch_prices=fetch_prices,
                allow_ocr=allow_ocr,
                kap_directory=directory,
            )
            packs[identity.fund_code] = pack
            sess.stats.funds_ok += 1
        except Exception as exc:  # noqa: BLE001 — universe must continue
            sess.stats.funds_failed += 1
            sess.stats.failed_requests += 1
            pack = {
                "fund_code": identity.fund_code,
                "identity_status": IDENTITY_UNRESOLVED,
                "errors": [str(exc)[:240]],
                "review_reasons": ["SOURCE_ERROR"],
                "production_persist": False,
                "evidence_recovery_version": EVIDENCE_RECOVERY_VERSION,
            }
            _write_pack(identity.fund_code, pack)
            packs[identity.fund_code] = pack
        if on_fund:
            on_fund(identity.fund_code, packs[identity.fund_code])
    sess.stats.runtime_ms = int((time.monotonic() - started) * 1000)
    return packs, sess.stats


def _pack_is_reusable(pack: Mapping[str, Any], identity: TurkiyeFundUniverseIdentity) -> bool:
    version = int(pack.get("evidence_recovery_version") or 0)
    if version not in ACCEPTED_PACK_VERSIONS:
        return False
    if pack.get("fund_code") != identity.fund_code:
        return False
    if pack.get("production_persist"):
        return False
    if pack.get("pilot_frozen") and identity.fund_code in PILOT_TEFAS_FUND_CODES:
        return True
    if "SOURCE_ERROR" in tuple(pack.get("review_reasons") or ()):
        return False
    if pack.get("identity_status") != IDENTITY_RESOLVED:
        return False
    docs = dict(pack.get("documents") or {})
    ybf = (docs.get("BILGI_FORMU") or {}).get("file_oid") or pack.get("ybf_url")
    if identity.kap_disclosure_index and pack.get("kap_disclosure_index") not in {
        identity.kap_disclosure_index,
        None,
    }:
        return False
    return bool(ybf or pack.get("pdr_file_oid"))


def _pack_needs_tefas_only(pack: Mapping[str, Any]) -> bool:
    """KAP failed but the fund code is known; fill official TEFAS history without re-hitting KAP."""
    if pack.get("evidence_recovery_version") != EVIDENCE_RECOVERY_VERSION:
        return False
    if pack.get("pilot_frozen") or pack.get("production_persist"):
        return False
    if pack.get("tefas_price_rows"):
        return False
    reasons = tuple(pack.get("review_reasons") or ())
    return "SOURCE_ERROR" in reasons or pack.get("identity_status") != IDENTITY_RESOLVED
