from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import streamlit as st

from services.investment_thesis_contract import InvestmentThesisView
from services.ui_formatters import format_datetime_tr

_STATUS_LABELS = {
    "SUPPORTED": "Destekleniyor",
    "MIXED": "Karışık",
    "WEAKENING": "Zayıflıyor",
    "INSUFFICIENT_DATA": "Yetersiz veri",
}
_CONFIDENCE_LABELS = {
    "HIGH": "Yüksek",
    "MEDIUM": "Orta",
    "LOW": "Düşük",
}
_VALUATION_LABELS = {
    "VALUATION_SUPPORTIVE": "Değerleme tarihsel medyanın altında veya destekleyici",
    "VALUATION_NEUTRAL": "Değerleme tarihsel medyana yakın",
    "VALUATION_DEMANDING": "Değerleme tarihsel medyanın üzerinde",
    "VALUATION_UNAVAILABLE": "Değerleme bağlamı sınırlı",
}
_EARNINGS_LABELS = {
    "EARNINGS_SUPPORT": "Kazanç görünümü destekleyici",
    "EARNINGS_MIXED": "Kazanç görünümü karışık",
    "EARNINGS_WEAKENING": "Kazanç görünümü zayıflıyor",
    "EARNINGS_UNAVAILABLE": "Kazanç bağlamı yok",
}
_BALANCE_LABELS = {
    "SUPPORT_DOMINANT": "Destek ağırlıklı",
    "BALANCED": "Dengeli",
    "WEAKNESS_DOMINANT": "Zayıflık ağırlıklı",
    "INSUFFICIENT_DATA": "Yetersiz kanıt",
}


def render_investment_thesis_section(
    view: InvestmentThesisView,
    *,
    history: Tuple[Dict[str, Any], ...] = (),
    history_unavailable_message: Optional[str] = None,
    save_message: Optional[str] = None,
    save_skipped_duplicate: bool = False,
    save_failed: bool = False,
) -> bool:
    st.subheader("Yatırım Tezi")
    cols = st.columns(3)
    cols[0].metric("Tez durumu", _STATUS_LABELS.get(view.thesis_status, view.thesis_status))
    cols[1].metric("Güven", _CONFIDENCE_LABELS.get(view.confidence, view.confidence))
    cols[2].metric(
        "Kanıt dengesi",
        _BALANCE_LABELS.get(
            view.decision_intelligence.evidence_balance
            if view.decision_intelligence
            else "INSUFFICIENT_DATA",
            "—",
        ),
    )

    st.markdown(f"**Ana yatırım sorusu:** {view.key_question}")
    st.write(view.thesis_summary)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Kanıtlar lehine")
        if view.supporting_evidence:
            for item in view.supporting_evidence[:5]:
                st.success(item.statement)
        else:
            st.write("Belirgin destekleyici kanıt yok.")
    with right:
        st.markdown("#### Kanıtlar aleyhine")
        if view.weakening_evidence:
            for item in view.weakening_evidence[:5]:
                st.error(item.statement)
        else:
            st.write("Belirgin zayıflatan kanıt yok.")

    st.markdown("#### Değerleme gerilimi")
    st.write(_VALUATION_LABELS.get(view.valuation_context, view.valuation_context))
    if view.expectation_tensions:
        for tension in view.expectation_tensions[:3]:
            st.info(tension.statement)

    st.markdown("#### Ne değişti?")
    if view.change_summary:
        for change in view.change_summary[:8]:
            st.markdown(f"- {change.statement}")
    elif history:
        st.caption("Önceki kayda göre anlamlı yapısal değişiklik tespit edilmedi.")
    else:
        st.caption("Karşılaştırma için kayıtlı önceki tez yok.")

    st.markdown("#### Riskler")
    if view.risks:
        for risk in view.risks[:5]:
            st.warning(risk.statement)
    else:
        st.write("Kayıtlı materyal risk yok.")

    st.markdown("#### Katalizörler")
    if view.catalysts:
        for catalyst in view.catalysts[:5]:
            date_label = catalyst.expected_date or "Tarih bilinmiyor"
            st.markdown(f"- **{date_label}** — {catalyst.description} ({catalyst.status})")
    else:
        st.write("Bilinen katalizör yok.")

    st.markdown("#### Tezi geçersiz kılacak koşullar")
    if view.invalidation_conditions:
        for condition in view.invalidation_conditions[:6]:
            st.markdown(f"- {condition.statement}")
    else:
        st.write("Tanımlı geçersiz kılma koşulu yok.")

    st.markdown("#### Varsayımlar")
    if view.assumptions:
        for assumption in view.assumptions:
            status = {
                "SUPPORTED": "Destekleniyor",
                "UNVERIFIED": "Doğrulanmadı",
                "CHALLENGED": "Sorgulanıyor",
            }.get(assumption.status, assumption.status)
            st.markdown(f"- *{assumption.statement}* — {status}")
    else:
        st.write("Açık varsayım kaydı yok.")

    st.markdown("#### İzleme planı")
    if view.monitoring_plan:
        rows = []
        for item in view.monitoring_plan[:8]:
            rows.append(
                {
                    "Metrik / Olay": item.metric_or_event,
                    "Neden önemli?": item.why_it_matters,
                    "Durum": item.current_state,
                    "Sonraki tarih": item.next_known_date or "—",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.write("İzleme maddesi yok.")

    st.markdown("#### Geçmiş")
    if history_unavailable_message:
        st.info(history_unavailable_message)
    elif history:
        for row in history[:5]:
            captured = format_datetime_tr(row.get("captured_at"))
            status = _STATUS_LABELS.get(row.get("thesis_status"), row.get("thesis_status"))
            st.caption(f"{captured} · {status}")
    else:
        st.caption("Henüz kayıtlı tez geçmişi yok.")

    if save_message:
        if save_failed:
            st.error(save_message)
        elif save_skipped_duplicate:
            st.info(save_message)
        else:
            st.success(save_message)

    return st.button(
        "Tezi kaydet",
        key=f"save_investment_thesis_{view.symbol}",
        type="secondary",
    )

def render_investment_thesis_technical_details(view: InvestmentThesisView) -> None:
    with st.expander("Teknik ayrıntılar"):
        st.code(view.thesis_version, language=None)
        st.write("Değerleme kodu:", view.valuation_context)
        st.write("Kazanç kodu:", view.earnings_context)
        if view.evidence_coverage:
            st.json(view.evidence_coverage.to_dict())
        if view.nabi_context:
            st.caption(view.nabi_context)
