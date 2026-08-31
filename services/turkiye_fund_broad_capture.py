"""Broad official KAP/TEFAS evidence capture for the discovered universe.

Per-fund isolation, incremental cache, polite HTTP. Research capture only.
Does not persist production Participation/FI snapshots, 8E, or New Money.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable, Mapping, Optional, Sequence

from services.fund_product_contract import IDENTITY_RESOLVED, IDENTITY_UNRESOLVED
from services.official_kap_fund import parse_kap_ybf_text
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
    TEFAS_PRICE_URL,
    TEFAS_RETURNS_URL,
    TEFAS_SNAPSHOT_URL,
    CaptureRunStats,
    OfficialCaptureSession,
    cache_identity,
    load_or_store,
    read_cached_payload,
    read_evidence_pack,
    write_cached_pdr_text,
    write_evidence_pack,
)
from services.turkiye_fund_universe_contract import TEFAS_STATUS_ACTIVE, TurkiyeFundUniverseIdentity

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
    identity = cache_identity(kind="kap_pdf_text", key=file_oid, published_at=published_at)
    cached = read_cached_payload("kap_pdf_text", identity)
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
        kind="kap_pdf_text",
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


def capture_tefas_prices(
    session: OfficialCaptureSession,
    fund_code: str,
    *,
    start: str,
    end: str,
) -> Optional[dict[str, Any]]:
    code = normalize_fund_code(fund_code)
    key = f"{code}|{start}|{end}"

    def _fetch() -> dict[str, Any]:
        payload = session.http_json(
            TEFAS_PRICE_URL,
            {"fonKodu": code, "baslangicTarihi": start, "bitisTarihi": end},
            referer="https://www.tefas.gov.tr/",
        )
        error = payload.get("errorMessage")
        rows = list(payload.get("resultList") or [])
        if error or not rows:
            return {"fonKodu": code, "available": False, "error": error or "empty_resultList"}
        return {"fonKodu": code, "available": True, "rows": rows}

    try:
        payload, _hit = load_or_store(
            kind="tefas_prices",
            key=key,
            published_at=f"{start}|{end}",
            fetcher=_fetch,
            stats=session.stats,
        )
    except Exception as exc:  # noqa: BLE001
        return {"fonKodu": code, "available": False, "error": str(exc)[:240]}
    return dict(payload)


def capture_one_fund(
    identity: TurkiyeFundUniverseIdentity,
    *,
    session: OfficialCaptureSession,
    catalog_rows: Sequence[Mapping[str, Any]],
    as_of: Optional[date] = None,
    fetch_prices: bool = True,
) -> dict[str, Any]:
    """Capture official evidence for one fund. Failures stay on this fund."""
    day = _as_of(as_of)
    code = identity.fund_code
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
    }
    if identity.tefas_status != TEFAS_STATUS_ACTIVE:
        reasons.append("TEFAS_INACTIVE")
        pack["identity_status"] = IDENTITY_UNRESOLVED
        write_evidence_pack(code, pack)
        return pack

    title = identity.fund_name or ""
    slug = kap_official_slug(code, title)
    pack["kap_slug"] = slug or None
    pack["ozet_url"] = kap_ozet_url(code, title) or None
    pack["genel_url"] = kap_genel_url(code, title) or None
    if not slug:
        reasons.append("IDENTITY_UNRESOLVED")
        pack["identity_status"] = IDENTITY_UNRESOLVED
        write_evidence_pack(code, pack)
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
        errors.append(f"KAP_OZET:{exc}"[:240])
        reasons.append("SOURCE_ERROR")
        reasons.append("IDENTITY_UNRESOLVED")
        pack["identity_status"] = IDENTITY_UNRESOLVED
        write_evidence_pack(code, pack)
        return pack

    if ozet.get("fund_code") and ozet["fund_code"] != code:
        reasons.append("IDENTITY_UNRESOLVED")
        pack["identity_status"] = IDENTITY_UNRESOLVED
        pack["ozet"] = {"fund_code": ozet.get("fund_code")}
        write_evidence_pack(code, pack)
        return pack

    pack["identity_status"] = IDENTITY_RESOLVED if ozet.get("resolved") else IDENTITY_UNRESOLVED
    pack["founder"] = ozet.get("founder") or identity.founder
    pack["official_name"] = ozet.get("official_name") or identity.fund_name
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
            if key in {"kpy81_acc1_ISIN", "kpy81_acc1_kurucu_unvan", "kpy81_acc1_fon_sem_tur"}
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"KAP_GENEL:{exc}"[:240])
        reasons.append("SOURCE_ERROR")

    ybf_oid = ozet.get("ybf_file_oid")
    izahname_oid = ozet.get("izahname_file_oid")
    ybf_text = None
    izahname_text = None
    if ybf_oid:
        ybf_text, ybf_meta, _hit = _safe_pdf(session, ybf_oid, referer=pack["ozet_url"], errors=errors, reasons=reasons)
        pack["ybf_url"] = kap_file_url(ybf_oid)
        pack["ybf_sha256"] = ybf_meta
        if ybf_text is None and ybf_meta:
            errors.append(f"YBF_TEXT:{ybf_meta}"[:240])
    else:
        reasons.append("YBF_MISSING")
    if izahname_oid:
        izahname_text, izah_meta, _hit = _safe_pdf(
            session, izahname_oid, referer=pack["ozet_url"], errors=errors, reasons=reasons
        )
        pack["izahname_url"] = kap_file_url(izahname_oid)
        pack["izahname_sha256"] = izah_meta

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
        }
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
    if returns and not returns.get("available"):
        # Official point-in-time returns unavailable; daily history is separate.
        pass

    if fetch_prices:
        start = date(day.year - 1, day.month, min(day.day, 28)).isoformat()
        prices = capture_tefas_prices(session, code, start=start, end=day.isoformat())
        pack["tefas_prices"] = {
            "available": bool(prices and prices.get("available")),
            "error": (prices or {}).get("error"),
            "row_count": len(list((prices or {}).get("rows") or [])),
        }
        if not (prices and prices.get("available")):
            reasons.append("HISTORY_INSUFFICIENT")
            pack["tefas_price_rows"] = []
        else:
            pack["tefas_price_rows"] = list(prices.get("rows") or [])

    pack["review_reasons"] = list(dict.fromkeys(reasons))
    pack["errors"] = list(dict.fromkeys(errors))
    write_evidence_pack(code, pack)
    return pack


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
    limit: Optional[int] = None,
    fetch_prices: bool = True,
    on_fund: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> tuple[dict[str, dict[str, Any]], CaptureRunStats]:
    active = [row for row in identities if row.tefas_status == TEFAS_STATUS_ACTIVE]
    if limit is not None:
        active = active[: int(limit)]
    sess = session or OfficialCaptureSession(live=live, min_gap_sec=0.35 if live else 0.0)
    started = time.monotonic()
    packs: dict[str, dict[str, Any]] = {}
    for identity in active:
        sess.stats.funds_attempted += 1
        if resume:
            existing = read_evidence_pack(identity.fund_code)
            if existing and _pack_is_reusable(existing, identity):
                sess.stats.cache_hits += 1
                sess.stats.unchanged_documents += 1
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
            }
            write_evidence_pack(identity.fund_code, pack)
            packs[identity.fund_code] = pack
        if on_fund:
            on_fund(identity.fund_code, packs[identity.fund_code])
    sess.stats.runtime_ms = int((time.monotonic() - started) * 1000)
    _ = CACHE_DIR
    return packs, sess.stats


def _pack_is_reusable(pack: Mapping[str, Any], identity: TurkiyeFundUniverseIdentity) -> bool:
    if pack.get("fund_code") != identity.fund_code:
        return False
    if pack.get("production_persist"):
        return False
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
