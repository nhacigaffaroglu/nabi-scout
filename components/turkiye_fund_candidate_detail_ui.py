from __future__ import annotations


_FINAL_DISPLAY_LABELS = {
    "multi_asset": "Karma / çoklu varlık",
    "MIXED_MULTI_ASSET_PARTICIPATION_FUND": "Karma / çoklu varlık",
    "ACTIVE": "Aktif",
    "INACTIVE": "Pasif",
    "UNPROVEN": "Doğrulanmadı",
    "FUND": "Fon",
    "TR": "Türkiye",
    True: "Evet",
    False: "Hayır",
}


def _final_display(value):
    if value in _FINAL_DISPLAY_LABELS:
        return _FINAL_DISPLAY_LABELS[value]
    return value

from typing import Any

import pandas as pd
import streamlit as st

from services.turkiye_fund_candidate_detail import TurkiyeFundCandidateDetail


def _pct(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}%".replace(".", ",")


def _ratio(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}".replace(".", ",")


_EXCLUSION_LABELS = {
    "SCANNER_NOT_READY": "Scanner hazır değil",
    "PARTICIPATION_NOT_UYGUN": "Katılım uygunluğu onaylı değil",
    "RESEARCH_NOT_ALLOWED": "Araştırma izni kapalı",
    "FI_SCORE_NOT_PUBLISHABLE": "FI skoru yayımlanabilir değil",
}

_GATE_LABELS = {
    "SCANNER_READY": "Scanner hazır",
    "PARTICIPATION_UYGUN": "Katılım uygun",
    "RESEARCH_ALLOWED": "Araştırmaya izin",
    "FI_SCORE_PUBLISHABLE": "FI skoru yayımlanabilir",
}

_SCANNER_LABELS = {
    "READY": "Hazır",
    "REVIEW_REQUIRED": "İnceleme",
    "PARTIAL": "Kısmi",
    "BLOCKED": "Bloke",
}

_FI_STATE_LABELS = {
    "ATTRACTIVE": "Çekici",
    "WATCH": "İzle",
    "NEUTRAL": "Nötr",
    "CAUTION": "Dikkat",
    "AVOID": "Kaçın",
    "INSUFFICIENT_DATA": "Yetersiz veri",
}

_PROFILE_LABELS = {
    "EQUITY_PARTICIPATION_FUND": "Hisse senedi",
    "LIQUIDITY_PARTICIPATION_FUND": "Likidite",
    "SUKUK_PARTICIPATION_FUND": "Kira sertifikası",
    "PRECIOUS_METALS_PARTICIPATION_FUND": "Kıymetli maden",
    "REAL_ESTATE_PARTICIPATION_FUND": "Gayrimenkul",
    "MIXED_MULTI_ASSET_PARTICIPATION_FUND": "Karma / çoklu varlık",
}

_CATEGORY_LABELS = {
    "equity": "Hisse senedi",
    "liquidity": "Likidite",
    "sukuk": "Kira sertifikaları",
    "precious_metals": "Kıymetli maden",
    "real_estate": "Gayrimenkul",
    "mixed_multi_asset": "Karma / çoklu varlık",
}

_EXPOSURE_LABELS = {
    "equity": "Hisse senedi",
    "sukuk": "Kira sertifikaları",
    "precious_metals": "Kıymetli maden",
    "real_estate": "Gayrimenkul",
    "cash_like": "Nakit benzeri",
    "mixed_multi_asset": "Karma / çoklu varlık",
}

_PEER_LABELS = {
    "PEER_CATEGORY": "Kategori benzerleri",
    "OVERALL_RESEARCH": "Tüm araştırma evreni",
}

_REASON_LABELS = {
    "PDR_RECONCILIATION_FAILED": "PDR ağırlıkları uzlaştırılamadı",
    "PDR_WEIGHTS_UNRECONCILED": "PDR ağırlıkları uzlaştırılamadı",
    "PARTICIPATION_REVIEW": "Katılım uygunluğu manuel inceleme gerektiriyor",
    "MATERIAL_CONTRADICTION": "Kaynaklar arasında önemli çelişki var",
    "HOLDING_GROUP_OUTSIDE_MANDATE": "Fon görev tanımı dışında varlık grubu tespit edildi",
    "ECONOMIC_EXPOSURE_UNKNOWN": "Ekonomik maruziyet belirlenemedi",
    "PDR_PARSE_INCOMPLETE": "PDR ayrıştırması tamamlanamadı",
    "PDR_MISSING": "PDR verisi eksik",
    "HISTORY_INSUFFICIENT": "Geçmiş veri yetersiz",
    "FI_INSUFFICIENT_DATA": "FI değerlendirmesi için veri yetersiz",
    "SOURCE_STALE": "Kaynak veri güncel değil",
    "SOURCE_ERROR": "Kaynak veride hata var",
}


def _label(mapping: dict[str, str], value: str | None) -> str:
    if not value:
        return "—"
    return mapping.get(value, str(_final_display(value)).replace("_", " ").title())


def _humanize_evidence_code(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"

    code, sep, detail = raw.partition(":")
    label = _REASON_LABELS.get(
        code,
        code.replace("_", " ").title(),
    )

    if not sep or not detail:
        return label

    detail_labels = {
        "FUND": "Fon",
        "LEASE_CERTIFICATE": "Kira sertifikası",
        "EQUITY": "Hisse senedi",
        "PRECIOUS_METALS": "Kıymetli maden",
        "REAL_ESTATE": "Gayrimenkul",
        "CASH": "Nakit",
    }

    readable_detail = ", ".join(
        detail_labels.get(
            item.strip(),
            item.strip().replace("_", " ").title(),
        )
        for item in detail.split(",")
        if item.strip()
    )

    return f"{label} ({readable_detail})" if readable_detail else label


def _display_gate_value(value: Any) -> str:
    if value is True:
        return "Evet"
    if value is False:
        return "Hayır"
    if value is None:
        return "—"

    mapping = {
        "READY": "Hazır",
        "REVIEW_REQUIRED": "İnceleme gerekli",
        "PARTIAL": "Kısmi",
        "BLOCKED": "Bloke",
        "finite numeric FI score": "Geçerli sayısal FI skoru",
    }

    return mapping.get(str(_final_display(value)), str(_final_display(value)))


def _humanize_reason(reason: str | None) -> str:
    if not reason:
        return "Açıklama yok."

    raw = str(reason).strip()

    if raw == (
        "READY: canonical FI score; "
        "Participation is a gate, not an alpha factor."
    ):
        return (
            "Hazır: FI skoru yayımlanabilir. "
            "Katılım uygunluğu adaylık için zorunlu bir kapıdır; "
            "FI skorunu yükselten bir faktör değildir."
        )

    if raw.startswith("Review required:"):
        payload = raw.split(":", 1)[1].strip()
        items = [item.strip() for item in payload.split(",") if item.strip()]

        # Preserve colon-qualified codes such as:
        # HOLDING_GROUP_OUTSIDE_MANDATE:FUND,LEASE_CERTIFICATE
        normalized: list[str] = []
        i = 0
        while i < len(items):
            item = items[i]
            if ":" in item:
                base, suffix = item.split(":", 1)
                suffix_items = [suffix]
                j = i + 1
                while j < len(items) and items[j] in {
                    "FUND",
                    "LEASE_CERTIFICATE",
                    "EQUITY",
                    "PRECIOUS_METALS",
                    "REAL_ESTATE",
                    "CASH",
                }:
                    suffix_items.append(items[j])
                    j += 1
                normalized.append(
                    base + ":" + ",".join(suffix_items)
                )
                i = j
                continue
            normalized.append(item)
            i += 1

        readable = []
        seen = set()
        for item in normalized:
            label = _humanize_evidence_code(item)
            if label not in seen:
                readable.append(label)
                seen.add(label)

        return "İnceleme gerekli: " + " · ".join(readable)

    return _humanize_evidence_code(raw)


def render_turkiye_fund_candidate_detail(
    detail: TurkiyeFundCandidateDetail,
) -> None:
    st.caption(
        "Araştırma görünümü. Alım/satım, 8E, New Money veya portföy tahsis kararı değildir."
    )

    if detail.candidate_eligible:
        st.success(
            f"FUND14B aday kapıları açık · Aday sırası "
            f"#{detail.candidate_rank}/{detail.candidate_count}"
        )
    else:
        readable = [
            _EXCLUSION_LABELS.get(reason, reason)
            for reason in detail.exclusion_reasons
        ]
        st.warning(
            "FUND14B aday kapıları kapalı · "
            + " · ".join(readable)
        )

        with st.expander("Teknik kapı kodları"):
            for reason in detail.exclusion_reasons:
                st.code(reason)

    cols = st.columns(5)
    cols[0].metric(
        "Aday sırası",
        f"#{detail.candidate_rank}" if detail.candidate_rank is not None else "—",
    )
    cols[1].metric(
        "FI skoru",
        (
            f"{detail.fi_score:.2f}".replace(".", ",")
            if detail.fi_score is not None
            else "—"
        ),
    )
    cols[2].metric(
        "FI durumu",
        _label(_FI_STATE_LABELS, detail.fi_state),
    )
    cols[3].metric(
        "Katılım",
        detail.participation or "—",
    )
    cols[4].metric(
        "Scanner durumu",
        _label(_SCANNER_LABELS, detail.scanner_status),
    )

    st.markdown("### Neden bu durumda?")
    st.write(_humanize_reason(detail.reason))

    with st.expander("Teknik açıklama"):
        st.code(detail.reason or "—")

    gate_rows = [
        {
            "Kontrol": _GATE_LABELS.get(gate.gate, gate.gate),
            "Sonuç": "Geçti" if gate.passed else "Geçmedi",
            "Gözlenen": _display_gate_value(gate.observed),
            "Gerekli": _display_gate_value(gate.required),
        }
        for gate in detail.gates
    ]
    st.dataframe(
        pd.DataFrame(gate_rows),
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("### Araştırma bağlamı")
    a, b, c, d = st.columns(4)
    a.metric("Kategori", _label(_CATEGORY_LABELS, detail.category))
    b.metric("FI profili", _label(_PROFILE_LABELS, detail.fi_profile))
    c.metric("Maruziyet", _label(_EXPOSURE_LABELS, detail.exposure))
    d.metric("Karşılaştırma", _label(_PEER_LABELS, detail.peer_view))

    a, b, c, d = st.columns(4)
    a.metric("Güven", _ratio(detail.confidence))
    b.metric("Veri tamlığı", _ratio(detail.data_completeness))
    c.metric("1Y getiri", _pct(detail.return_1y))
    d.metric("Maks. düşüş", _pct(detail.max_drawdown))

    identity = detail.identity or {}
    if identity:
        st.markdown("### Fon kimliği / snapshot")
        rows: list[dict[str, Any]] = [
            {"Alan": "Fon", "Değer": detail.fund_code},
            {"Alan": "Ad", "Değer": detail.fund_name or "—"},
            {"Alan": "Kurucu/Yönetici", "Değer": detail.founder or "—"},
            {"Alan": "Enstrüman", "Değer": identity.get("instrument") or "—"},
            {"Alan": "Piyasa", "Değer": identity.get("market") or "—"},
            {"Alan": "TEFAS durumu", "Değer": identity.get("tefas_status") or "—"},
            {"Alan": "Fiyat tarihi", "Değer": identity.get("price_date") or "—"},
            {"Alan": "Birim fiyat", "Değer": identity.get("unit_price")},
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.markdown("### Kanıt / durum")

    universe_labels = {
        "DISCOVERED": "Keşfedildi",
        "ACTIVE": "Aktif",
        "ANALYZABLE": "Analiz edilebilir",
        "PARTICIPATION_ELIGIBLE": "Katılım açısından uygun",
        "SCANNABLE": "Scanner değerlendirmesine uygun",
    }

    state_cols = st.columns(2)
    with state_cols[0]:
        st.markdown("**Evren durumları**")
        if detail.universe_states:
            for state in detail.universe_states:
                st.caption(
                    f"• {universe_labels.get(state, state)}"
                )
        else:
            st.caption("—")

    with state_cols[1]:
        st.markdown("**Eksik / bloklayan kanıt**")
        if detail.missing_evidence:
            for reason in detail.missing_evidence:
                st.caption(
                    f"• {_humanize_evidence_code(reason)}"
                )

            with st.expander("Teknik kanıt kodları"):
                for reason in detail.missing_evidence:
                    st.code(reason)
        else:
            st.caption("Yok.")

    st.markdown("### Veri kökeni")
    st.caption(f"Scanner veri tarihi: {detail.as_of or '—'}")
    st.caption(f"Hesaplama tarihi: {detail.calculated_at or '—'}")
    st.caption(
        "Sıralama kuralı: FI skoru ↓ → veri tamlığı ↓ → "
        "güven ↓ → fon kodu A-Z"
    )

    with st.expander("Araştırma güvenlik sınırları"):
        firewall_rows = [
            {"Kontrol": "Yalnız araştırma", "Durum": detail.research_only},
            {"Kontrol": "Eşik önerildi", "Durum": detail.threshold_proposed},
            {"Kontrol": "Eşik kilitlendi", "Durum": detail.threshold_locked},
            {
                "Kontrol": "Öneri bandı uygulandı",
                "Durum": detail.recommendation_band_applied,
            },
            {
                "Kontrol": "İşlem yetkisi",
                "Durum": detail.execution_authority,
            },
            {
                "Kontrol": "Production persistence",
                "Durum": detail.production_persist,
            },
        ]
        st.dataframe(
            pd.DataFrame(firewall_rows),
            hide_index=True,
            use_container_width=True,
        )
