"""Plotly figures in the project's design tokens.

Rules followed throughout: one axis per chart, text in ink colours (never
the series colour), thin marks with rounded data ends, hover on every
mark, recessive grid. Single-series bar charts use one hue; the label on
the axis carries identity.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from schichtwechsel.ui.theme import FONT, tokens

# Bundesländer as equal tiles, placed roughly where they sit (column, row).
TILES = {
    "SCHLESWIG_HOLSTEIN": (2, 0),
    "BREMEN": (1, 1),
    "HAMBURG": (2, 1),
    "MECKLENBURG_VORPOMMERN": (3, 1),
    "NORDRHEIN_WESTFALEN": (0, 2),
    "NIEDERSACHSEN": (1, 2),
    "SACHSEN_ANHALT": (2, 2),
    "BERLIN": (3, 2),
    "BRANDENBURG": (4, 2),
    "RHEINLAND_PFALZ": (0, 3),
    "HESSEN": (1, 3),
    "THUERINGEN": (2, 3),
    "SACHSEN": (3, 3),
    "SAARLAND": (0, 4),
    "BADEN_WUERTTEMBERG": (1, 4),
    "BAYERN": (2, 4),
}


def _layout(fig: go.Figure, mode: str, lang: str, height: int) -> go.Figure:
    tk = tokens(mode)
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "color": tk["ink2"], "size": 13},
        separators=",." if lang == "de" else ".,",
        hoverlabel={
            "bgcolor": tk["surface"],
            "bordercolor": tk["baseline"],
            "font": {"family": FONT, "color": tk["ink"], "size": 13},
        },
        showlegend=False,
    )
    fig.update_xaxes(
        gridcolor=tk["grid"],
        zerolinecolor=tk["baseline"],
        linecolor=tk["baseline"],
        tickfont={"color": tk["muted"]},
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor=tk["grid"],
        zerolinecolor=tk["baseline"],
        linecolor=tk["baseline"],
        tickfont={"color": tk["ink2"]},
        automargin=True,
    )
    return fig


def hbar(
    labels: list[str],
    values: list[float],
    text: list[str],
    hover: list[str],
    mode: str,
    lang: str,
    highlight: str | None = None,
) -> go.Figure:
    """Ranked horizontal bars, one series. A highlighted bar keeps the hue, others recede."""
    tk = tokens(mode)
    order = sorted(range(len(values)), key=lambda i: values[i])
    colors = [
        tk["series"][0] if highlight is None or labels[i] == highlight else tk["sequential"][2]
        for i in order
    ]
    fig = go.Figure(
        go.Bar(
            x=[values[i] for i in order],
            y=[labels[i] for i in order],
            orientation="h",
            marker={"color": colors, "cornerradius": 4, "line": {"width": 0}},
            text=[text[i] for i in order],
            textposition="outside",
            textfont={"color": tk["ink"]},
            cliponaxis=False,
            hovertext=[hover[i] for i in order],
            hoverinfo="text",
        )
    )
    fig.update_layout(bargap=0.38)
    fig.update_xaxes(visible=False, range=[0, max(values) * 1.18 if values else 1])
    fig.update_yaxes(showgrid=False, ticks="", ticklabelstandoff=6, automargin=True)
    return _layout(fig, mode, lang, height=48 + 34 * len(values))


def tile_map(frame: pd.DataFrame, abbr: dict, hover_lines, mode: str, lang: str) -> go.Figure:
    """Diverging tile grid: 100 is the national rate, blue below, amber above."""
    tk = tokens(mode)
    cols = max(c for c, _ in TILES.values()) + 1
    rows = max(r for _, r in TILES.values()) + 1
    z = [[None] * cols for _ in range(rows)]
    hover = [[""] * cols for _ in range(rows)]
    by_region = frame.set_index("region")
    cells = []
    for region, (c, r) in TILES.items():
        if region in by_region.index:
            row = by_region.loc[region]
            z[r][c] = float(row["pressure_index"])
            hover[r][c] = hover_lines(region, row)
            cells.append((region, c, r, float(row["pressure_index"])))
    spread = max((abs(v - 100) for *_, v in cells), default=50) or 50
    ramp = tk["diverging"]
    scale = [[i / (len(ramp) - 1), color] for i, color in enumerate(ramp)]
    fig = go.Figure(
        go.Heatmap(
            z=z,
            hovertext=hover,
            hoverinfo="text",
            colorscale=scale,
            zmid=100,
            zmin=100 - spread,
            zmax=100 + spread,
            xgap=4,
            ygap=4,
            showscale=False,
        )
    )
    # labels as annotations, so strong fills can take light text
    for region, c, r, value in cells:
        # light mode: only the strong blue end is dark enough for light text; amber stays light
        light_text = mode != "dark" and value < 100 and (100 - value) / spread > 0.55
        color = tk["on_dark_fill"] if light_text else tk["ink"]
        fig.add_annotation(
            x=c,
            y=r,
            text=f"<b>{abbr[region]}</b><br>{value:.0f}",
            showarrow=False,
            font={"family": FONT, "size": 13, "color": color},
        )
    fig.update_xaxes(visible=False, constrain="domain")
    fig.update_yaxes(visible=False, autorange="reversed", scaleanchor="x", constrain="domain")
    return _layout(fig, mode, lang, height=420)


def heatmap(
    frame: pd.DataFrame,
    x: str,
    y: str,
    value: str,
    x_labels: dict,
    y_labels: dict,
    hover,
    mode: str,
    lang: str,
) -> go.Figure:
    """Sequential one-hue matrix, for shares between 0 and 1."""
    tk = tokens(mode)
    pivot = frame.pivot(index=y, columns=x, values=value)
    pivot = pivot.loc[pivot.mean(axis=1).sort_values().index]
    ramp = tk["sequential"]
    scale = [[i / (len(ramp) - 1), color] for i, color in enumerate(ramp)]
    text = [[f"{v:.0%}" if pd.notna(v) else "" for v in row] for row in pivot.to_numpy()]
    if lang == "de":
        text = [[s.replace("%", " %") for s in row] for row in text]
    fig = go.Figure(
        go.Heatmap(
            z=pivot.to_numpy(),
            x=[x_labels.get(c, c) for c in pivot.columns],
            y=[y_labels.get(r, r) for r in pivot.index],
            text=text,
            texttemplate="%{text}",
            textfont={"family": FONT, "size": 11},
            customdata=[[hover(r, c) for c in pivot.columns] for r in pivot.index],
            hovertemplate="%{customdata}<extra></extra>",
            colorscale=scale,
            zmin=0,
            zmax=1,
            xgap=2,
            ygap=2,
            showscale=False,
        )
    )
    fig.update_xaxes(side="top", showgrid=False, tickfont={"color": tk["ink2"]})
    fig.update_yaxes(showgrid=False)
    return _layout(fig, mode, lang, height=40 + 28 * len(pivot.index))


def dumbbell(
    labels: list[str], median: list[float], p80: list[float], hover: list[str], mode: str, lang: str
) -> go.Figure:
    """Median as a dot, a thin line out to the P80."""
    tk = tokens(mode)
    order = sorted(range(len(median)), key=lambda i: median[i])
    fig = go.Figure()
    for i in order:
        fig.add_trace(
            go.Scatter(
                x=[median[i], p80[i]],
                y=[labels[i]] * 2,
                mode="lines",
                line={"color": tk["sequential"][2], "width": 2},
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[median[i] for i in order],
            y=[labels[i] for i in order],
            mode="markers",
            marker={
                "size": 10,
                "color": tk["series"][0],
                "line": {"width": 2, "color": tk["surface"]},
            },
            hovertext=[hover[i] for i in order],
            hoverinfo="text",
        )
    )
    fig.update_xaxes(rangemode="tozero", ticksuffix=" days" if lang == "en" else " Tage")
    fig.update_yaxes(showgrid=False)
    return _layout(fig, mode, lang, height=48 + 26 * len(labels))


def small_multiples(
    frame: pd.DataFrame, facet: str, x: str, y: str, facet_labels: dict, mode: str, lang: str
) -> go.Figure:
    """One line per panel, shared y scale, so panels compare at a glance."""
    tk = tokens(mode)
    facets = list(frame[facet].drop_duplicates())
    fig = make_subplots(
        rows=1,
        cols=len(facets),
        shared_yaxes=True,
        horizontal_spacing=0.03,
        subplot_titles=[facet_labels.get(f, f) for f in facets],
    )
    for i, f in enumerate(facets, start=1):
        part = frame[frame[facet] == f]
        fig.add_trace(
            go.Scatter(
                x=part[x],
                y=part[y],
                mode="lines",
                line={"color": tk["series"][0], "width": 2},
                hovertemplate="%{x|%b %Y}: %{y:.1%}<extra>" + facet_labels.get(f, f) + "</extra>",
            ),
            row=1,
            col=i,
        )
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    fig.update_xaxes(showgrid=False, nticks=3)
    fig.update_annotations(font={"family": FONT, "size": 13, "color": tk["ink"]})
    _layout(fig, mode, lang, height=240)
    fig.update_layout(margin={"t": 30})
    return fig


def agent_chart(spec: dict, mode: str, lang: str) -> go.Figure | None:
    """Chart requested by the analyst, drawn from its query rows only."""
    tk = tokens(mode)
    frame = pd.DataFrame(spec["rows"], columns=spec["columns"])
    if frame.empty:
        return None
    series = spec.get("series")
    groups = list(frame[series].drop_duplicates()) if series else [None]
    if len(groups) > len(tk["series"]):
        return None  # more series than validated colours: the table view carries it
    fig = go.Figure()
    for i, g in enumerate(groups):
        part = frame if g is None else frame[frame[series] == g]
        color = tk["series"][i]
        if spec["kind"] == "line":
            fig.add_trace(
                go.Scatter(
                    x=part[spec["x"]],
                    y=part[spec["y"]],
                    name=str(g or spec["y"]),
                    mode="lines",
                    line={"color": color, "width": 2},
                )
            )
        else:
            fig.add_trace(
                go.Bar(
                    x=part[spec["x"]],
                    y=part[spec["y"]],
                    name=str(g or spec["y"]),
                    marker={"color": color, "cornerradius": 4},
                )
            )
    _layout(fig, mode, lang, height=320)
    fig.update_layout(
        showlegend=len(groups) > 1,
        bargap=0.35,
        bargroupgap=0.08,
        legend={"orientation": "h", "y": 1.08, "font": {"color": tk["ink2"]}},
    )
    return fig
