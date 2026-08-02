from __future__ import annotations

from typing import Optional

import streamlit as st

from services.academy_content import (
    get_metric,
    interpret_metric,
)


def render_metric_card(
    key: str,
    value: Optional[float],
    *,
    value_format: str = ".2f",
) -> None:
    metric = get_metric(key)
    if not metric:
        return

    interpretation = interpret_metric(key, value)
    display_value = (
        "—"
        if value is None
        else format(float(value), value_format)
    )

    with st.container(border=True):
        top_left, top_right = st.columns([2.5, 1])

        with top_left:
            st.markdown(f"#### {metric['title']}")
            st.metric("Değer", display_value)

        with top_right:
            tone = interpretation["tone"]
            label = interpretation["label"]

            if tone == "positive":
                st.success(label)
            elif tone == "negative":
                st.error(label)
            else:
                st.warning(label)

        st.write(interpretation["comment"])
        st.caption(metric["short"])

        with st.expander("🎓 Basit anlat ve detayları göster"):
            st.markdown(f"**Basit anlat:** {metric['simple']}")
            st.markdown(f"**Neden önemli?** {metric['why']}")
            st.markdown(
                f"**Bu beni neden ilgilendiriyor?** "
                f"{metric['why_you_care']}"
            )

            st.markdown("**Genel yorum aralıkları:**")
            for label, range_text in metric["ranges"]:
                st.write(f"- {label}: {range_text}")

            st.warning(f"**Dikkat:** {metric['warning']}")


def render_metric_explanation(
    key: str,
    value: Optional[float],
    *,
    expanded: bool = False,
) -> None:
    metric = get_metric(key)
    if not metric:
        return

    interpretation = interpret_metric(key, value)

    with st.expander(
        f"📘 {metric['title']} — Bu ne demek?",
        expanded=expanded,
    ):
        st.markdown(f"**Sade anlatım:** {metric['simple']}")
        st.markdown(f"**Neden önemli?** {metric['why']}")
        st.markdown(
            f"**Bu şirketteki yorum:** "
            f"{interpretation['comment']}"
        )
        st.markdown(
            f"**Bu beni neden ilgilendiriyor?** "
            f"{metric['why_you_care']}"
        )

        st.markdown("**Genel değerlendirme aralıkları:**")
        for label, range_text in metric["ranges"]:
            st.write(f"- {label}: {range_text}")

        st.warning(f"**Dikkat:** {metric['warning']}")
