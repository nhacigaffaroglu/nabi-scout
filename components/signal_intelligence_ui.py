from __future__ import annotations

import streamlit as st

from services.signal_intelligence_contract import SignalIntelligenceContext


def render_signal_intelligence_section(context: SignalIntelligenceContext) -> None:
    st.subheader("Sinyal İstihbaratı")
    st.caption(
        "Olay bağlamı. Temel Security Intelligence skorunu değiştirmez, "
        "Katılım duvarını aşmaz ve al/sat üretmez. "
        f"{context.contract_version} · {context.engine_version}"
    )
    cols = st.columns(4)
    cols[0].metric("Maddi olay", str(context.snapshot_refs.material_signal_count))
    cols[1].metric("Doğrulanmamış", str(len(context.unverified_signals)))
    cols[2].metric("Son maddi olay", context.latest_material_event_at or "—")
    cols[3].metric("Özet", context.signal_summary or "—")
    if context.signal_risk_flags:
        st.caption("Sinyal risk bayrakları: " + ", ".join(context.signal_risk_flags))
    if not context.recent_signals:
        st.caption("Kayıtlı sinyal yok.")
        return
    rows = []
    for item in context.recent_signals:
        rows.append(
            {
                "Olay": item.event_type,
                "Başlık": item.headline or "—",
                "Kaynak otoritesi": item.source_authority,
                "Doğrulama": item.verification_status,
                "Maddilik": item.materiality,
                "Yön": item.direction,
                "Neden önemli": item.why_it_matters,
            }
        )
    st.markdown("**Son sinyaller / maddi olaylar**")
    st.dataframe(rows, use_container_width=True, hide_index=True)
    if context.material_signals:
        st.caption(
            "Maddi olaylar: "
            + ", ".join(item.event_id for item in context.material_signals[:5])
        )
