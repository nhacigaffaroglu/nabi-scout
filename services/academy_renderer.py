from __future__ import annotations

from typing import Optional

import streamlit as st

from services.financial_glossary import (
    get_metric,
    interpret_value,
)


def render_metric_explanation(
    key: str,
    value: Optional[float],
    *,
    expanded: bool = False,
) -> None:
    metric = get_metric(key)
    if not metric:
        return

    with st.expander(
        f"📘 {metric['title']} — Bu ne demek?",
        expanded=expanded,
    ):
        st.markdown(f"**Sade anlatım:** {metric['simple']}")
        st.markdown(f"**Neden önemli?** {metric['why']}")
        st.markdown(f"**Bu şirketteki yorum:** {interpret_value(key, value)}")

        ranges = metric.get("good_range", {})
        if ranges:
            st.markdown("**Genel değerlendirme aralıkları:**")
            for label, text in ranges.items():
                readable = {
                    "weak": "Zayıf",
                    "average": "Orta",
                    "good": "İyi",
                    "excellent": "Çok iyi",
                }.get(label, label)
                st.write(f"- {readable}: {text}")

        st.markdown(f"**Günlük hayattan örnek:** {metric['analogy']}")
        st.warning(f"**Dikkat:** {metric['caution']}")


def render_compact_help(
    key: str,
    value: Optional[float],
) -> None:
    metric = get_metric(key)
    if not metric:
        return

    st.caption(
        f"ⓘ {metric['simple']} "
        f"Bu şirkette: {interpret_value(key, value)}"
    )
