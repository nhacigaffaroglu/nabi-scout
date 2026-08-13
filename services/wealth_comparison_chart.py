from __future__ import annotations

from typing import Sequence

import altair as alt
import pandas as pd

from services.wealth_timeline_contract import NormalizedSeriesPoint

PORTFOLIO_SERIES_LABEL = "Portföy"
BENCHMARK_SERIES_LABEL = "SPY"
Y_AXIS_LABEL = "Normalize endeks (başlangıç = 100)"
X_AXIS_LABEL = "Anlık görüntü"


def build_benchmark_comparison_chart_frame(
    points: Sequence[NormalizedSeriesPoint],
) -> pd.DataFrame:
    """Build explicit long/wide chart input for normalized comparison."""
    if not points:
        raise ValueError("At least one normalized comparison point is required.")

    rows: list[dict[str, object]] = []
    for point in points:
        if point.portfolio_index is None or point.benchmark_index is None:
            raise ValueError("Normalized comparison points must include both series values.")
        rows.append(
            {
                "timestamp": pd.to_datetime(point.label_date, utc=True),
                PORTFOLIO_SERIES_LABEL: float(point.portfolio_index),
                BENCHMARK_SERIES_LABEL: float(point.benchmark_index),
            }
        )

    frame = pd.DataFrame(rows)
    frame[PORTFOLIO_SERIES_LABEL] = pd.to_numeric(frame[PORTFOLIO_SERIES_LABEL])
    frame[BENCHMARK_SERIES_LABEL] = pd.to_numeric(frame[BENCHMARK_SERIES_LABEL])
    return frame


def build_benchmark_comparison_altair_chart(frame: pd.DataFrame) -> alt.Chart:
    """Explicit Altair chart: timestamp on X, normalized index on Y."""
    melted = frame.melt(
        id_vars=["timestamp"],
        value_vars=[PORTFOLIO_SERIES_LABEL, BENCHMARK_SERIES_LABEL],
        var_name="Seri",
        value_name="Normalize endeks",
    )
    return (
        alt.Chart(melted)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "timestamp:T",
                title=X_AXIS_LABEL,
            ),
            y=alt.Y(
                "Normalize endeks:Q",
                title=Y_AXIS_LABEL,
                scale=alt.Scale(zero=False),
            ),
            color=alt.Color(
                "Seri:N",
                title="Seri",
                scale=alt.Scale(
                    domain=[PORTFOLIO_SERIES_LABEL, BENCHMARK_SERIES_LABEL],
                    range=["#1f77b4", "#ff7f0e"],
                ),
            ),
            tooltip=[
                alt.Tooltip("timestamp:T", title=X_AXIS_LABEL),
                alt.Tooltip("Normalize endeks:Q", title=Y_AXIS_LABEL, format=".2f"),
                alt.Tooltip("Seri:N", title="Seri"),
            ],
        )
    )
