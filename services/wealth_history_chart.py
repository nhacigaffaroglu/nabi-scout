from __future__ import annotations

from typing import Optional, Sequence

import altair as alt
import pandas as pd

from services.wealth_history_service import WealthHistoryPoint


def build_wealth_history_curve(
    points: Sequence[WealthHistoryPoint],
) -> Optional[alt.Chart]:
    """Observed snapshot points only — no daily fill, no interpolation of missing dates."""
    if len(points) < 2:
        return None
    frame = pd.DataFrame(
        {
            "captured_at": [pd.to_datetime(point.captured_at, utc=True) for point in points],
            "measurable_value": [float(point.priced_market_value) for point in points],
            "kısmi": ["Evet" if point.is_partial else "Hayır" for point in points],
        }
    )
    return (
        alt.Chart(frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("captured_at:T", title="Snapshot"),
            y=alt.Y("measurable_value:Q", title="Ölçülebilen servet", scale=alt.Scale(zero=False)),
            color=alt.Color(
                "kısmi:N",
                title="Kısmi değerleme",
                scale=alt.Scale(domain=["Hayır", "Evet"], range=["#2b6cb0", "#b86e00"]),
            ),
            tooltip=[
                alt.Tooltip("captured_at:T", title="Tarih"),
                alt.Tooltip("measurable_value:Q", title="Değer", format=",.2f"),
                alt.Tooltip("kısmi:N", title="Kısmi"),
            ],
        )
        .properties(height=220)
    )
