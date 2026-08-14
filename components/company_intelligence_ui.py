from __future__ import annotations

import streamlit as st

from services.company_intelligence_contract import CompanyIntelligenceView


def _metric(value, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return f"{value}{suffix}"


def render_company_intelligence_sections(view: CompanyIntelligenceView) -> None:
    st.subheader("Şirket Özeti")
    snapshot = view.business_snapshot
    if snapshot is None:
        st.info("Şirket profili şu anda kullanılamıyor.")
    else:
        cols = st.columns(4)
        cols[0].metric("Sektör", snapshot.sector or "—")
        cols[1].metric("Endüstri", snapshot.industry or "—")
        cols[2].metric("Piyasa Değeri", _metric(snapshot.market_cap))
        cols[3].metric("Borsa", snapshot.exchange or "—")
        if snapshot.description:
            st.caption(snapshot.description[:500])

    st.subheader("Finansal Eğilim")
    trends = view.financial_trends
    if trends is None or not trends.trends:
        st.info("Finansal eğilim verisi şu anda kullanılamıyor.")
    else:
        rows = []
        labels = {
            "revenue": "Gelir",
            "eps": "EPS",
            "operating_margin": "Faaliyet Marjı",
            "net_margin": "Net Marj",
            "free_cash_flow": "Serbest Nakit Akışı",
            "total_debt": "Toplam Borç",
        }
        for trend in trends.trends[:8]:
            rows.append(
                {
                    "Gösterge": labels.get(trend.metric, trend.metric),
                    "Son": _metric(trend.latest_value),
                    "Önceki": _metric(trend.previous_value),
                    "Değişim %": _metric(trend.pct_change, "%"),
                    "Yön": trend.direction,
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Son Finansallar / Earnings")
    earnings = view.earnings
    if earnings is None or not earnings.observations:
        st.info("Karşılaştırılabilir earnings değişimi bulunamadı.")
    else:
        for item in earnings.observations[:6]:
            st.markdown(f"- {item.statement}")
        if earnings.expectations.expectations_available:
            st.caption(
                "Beklenti verisi mevcut: EPS sürprizi "
                f"{_metric(earnings.expectations.eps_surprise_pct, '%')}"
            )
        else:
            st.caption("Beklenti/sürpriz verisi sağlayıcıdan alınamadı.")

    st.subheader("Değerleme")
    valuation = view.valuation
    if valuation is None or not valuation.metrics:
        st.info("Değerleme verisi şu anda kullanılamıyor.")
    else:
        rows = []
        position_labels = {
            "BELOW_HISTORICAL_RANGE": "Tarihsel aralığın altında",
            "BELOW_HISTORICAL_MEDIAN": "Tarihsel medyanın altında",
            "NEAR_HISTORICAL_MEDIAN": "Tarihsel medyana yakın",
            "ABOVE_HISTORICAL_MEDIAN": "Tarihsel medyanın üstünde",
            "ABOVE_HISTORICAL_RANGE": "Tarihsel aralığın üstünde",
            "INSUFFICIENT_DATA": "Yetersiz veri",
        }
        for metric in valuation.metrics:
            if not metric.meaningful and metric.current_value is None:
                continue
            rows.append(
                {
                    "Metrik": metric.label,
                    "Güncel": _metric(metric.current_value),
                    "Tarihsel Medyan": _metric(metric.historical_median),
                    "Prim %": _metric(metric.premium_to_median_pct, "%"),
                    "Bağlam": position_labels.get(metric.position, metric.position),
                }
            )
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("Anlamlı değerleme metriği üretilemedi.")

    st.subheader("Rakipler")
    peers = view.peers
    if peers is None or not peers.comparisons:
        st.info("Rakip karşılaştırması şu anda kullanılamıyor.")
    else:
        if peers.peer_symbols:
            st.caption("Rakip seti: " + ", ".join(peers.peer_symbols))
        rows = []
        for row in peers.comparisons:
            rows.append(
                {
                    "Metrik": row.metric,
                    "Şirket": _metric(row.company_value),
                    "Rakip Medyan": _metric(row.peer_median),
                    "Fark": _metric(row.difference),
                    "Örneklem": row.peer_count,
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Haberler ve Olaylar")
    news = view.news
    if news is None or not news.events:
        st.info("Haber verisi şu anda kullanılamıyor.")
    else:
        material = [event for event in news.events if event.materiality in {"MATERIAL", "THESIS_RELEVANT"}]
        relevant = [event for event in news.events if event.materiality == "RELEVANT"]
        noise = [event for event in news.events if event.materiality == "NOISE"]
        for event in material[:5]:
            st.markdown(f"**{event.headline}**")
            st.caption(
                f"{event.source or 'Kaynak yok'} · {event.category} · "
                f"{event.materiality}"
            )
        if relevant:
            with st.expander("Diğer ilgili haberler"):
                for event in relevant[:8]:
                    st.markdown(f"- {event.headline}")
        if noise:
            with st.expander("Düşük önem (gürültü)"):
                for event in noise[:8]:
                    st.markdown(f"- {event.headline}")

    st.subheader("Katalizörler")
    if not view.catalysts:
        st.info("Bilinen katalizör bulunamadı.")
    else:
        for item in view.catalysts[:8]:
            st.markdown(f"- **{item.catalyst_type}** · {item.description}")

    st.subheader("Risk Sinyalleri")
    if not view.factual_risks:
        st.caption("Belirgin risk sinyali üretilmedi.")
    else:
        for risk in view.factual_risks[:8]:
            st.markdown(f"- {risk.statement}")

    quality = view.data_quality
    if quality and (quality.warnings or quality.provider_failures or quality.partial_sections):
        with st.expander("Veri kalitesi"):
            for warning in quality.warnings:
                st.caption(warning)
            if quality.provider_failures:
                st.caption(
                    "Sağlayıcı kısıtları: "
                    + ", ".join(sorted(set(quality.provider_failures))[:6])
                )
