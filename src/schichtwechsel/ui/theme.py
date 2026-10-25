"""Design tokens for charts, per colour mode.

Same values as .streamlit/config.toml. Categorical slots: blue ("Nacht"),
amber ("Morgen"), teal. Validated in both modes: all-pairs CVD and normal
vision separation, contrast against the surface. See docs/design.md.
"""

from __future__ import annotations

FONT = "Schibsted Grotesk, system-ui, sans-serif"

TOKENS = {
    "light": {
        "surface": "#f7f5f0",
        "ink": "#1b1f24",
        "ink2": "#4d5560",
        "muted": "#8a8f96",
        "grid": "#e6e1d6",
        "baseline": "#c9c2b3",
        "series": ["#1f64b0", "#c7761a", "#2a9d8f"],
        "sequential": ["#e3ebf4", "#bcd0e8", "#8fb1da", "#5d8cc7", "#3469ab", "#1f4f8a", "#153a66"],
        "diverging": ["#1f64b0", "#6b93c9", "#a9bedd", "#e8e3d8", "#e3bf8c", "#d1954a", "#b86a14"],
        "on_dark_fill": "#ffffff",
        "on_light_fill": "#1b1f24",
    },
    "dark": {
        "surface": "#141a22",
        "ink": "#ece8df",
        "ink2": "#b9b4aa",
        "muted": "#8a8f96",
        "grid": "#232c38",
        "baseline": "#36404d",
        "series": ["#3f84d1", "#c27a22", "#2fa595"],
        "sequential": ["#23324a", "#2a4a7a", "#3466a8", "#4a83cc", "#6d9edb", "#9bbde8", "#c9dbf2"],
        "diverging": ["#4f8bd6", "#3a6aa6", "#2f4f78", "#2a313b", "#5c4a2e", "#94682c", "#c9862c"],
        "on_dark_fill": "#ffffff",
        "on_light_fill": "#141a22",
    },
}


def tokens(mode: str) -> dict:
    return TOKENS["dark" if mode == "dark" else "light"]
