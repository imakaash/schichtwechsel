"""UI text from locales/de.json and locales/en.json. Data stays in canonical codes."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import streamlit as st

LOCALES = Path(__file__).parent / "locales"
LANGUAGES = {"de": "Deutsch", "en": "English"}


@cache
def _load(lang: str) -> dict:
    return json.loads((LOCALES / f"{lang}.json").read_text("utf-8"))


def lang() -> str:
    return st.session_state.get("lang", "de")


def t(key: str, **values) -> str:
    node = _load(lang())
    for part in key.split("."):
        node = node[part]
    return node.format(**values) if values and isinstance(node, str) else node


def label(group: str, code: str) -> str:
    """Display name for a data code, falling back to the code itself."""
    return _load(lang()).get(group, {}).get(code, code)


def number(value: float, decimals: int = 0) -> str:
    text = f"{value:,.{decimals}f}"
    if lang() == "de":
        text = text.replace(",", " ").replace(".", ",").replace(" ", ".")
    return text


def percent(share: float, decimals: int = 0) -> str:
    return f"{number(share * 100, decimals)} %"
