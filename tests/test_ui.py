import json
from pathlib import Path

import pandas as pd
import pytest

from schichtwechsel.config import WAREHOUSE
from schichtwechsel.ui import charts

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "src/schichtwechsel/ui/locales"
APP = str(ROOT / "src/schichtwechsel/ui/app.py")


def keys(node, prefix=""):
    out = set()
    for k, v in node.items():
        out |= keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {f"{prefix}{k}"}
    return out


def test_locales_have_the_same_keys():
    de = json.loads((LOCALES / "de.json").read_text("utf-8"))
    en = json.loads((LOCALES / "en.json").read_text("utf-8"))
    assert keys(de) == keys(en)
    assert set(de["region"]) == set(charts.TILES)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_charts_render_in_both_modes(mode):
    bars = charts.hbar(["a", "b"], [2.0, 5.0], ["2", "5"], ["a", "b"], mode, "de")
    assert list(bars.data[0].y) == ["a", "b"]  # ascending, so the largest sits on top

    pressure = pd.DataFrame(
        {"region": list(charts.TILES), "pressure_index": range(50, 50 + 16 * 10, 10)}
    )
    tiles = charts.tile_map(
        pressure, {r: r[:2] for r in charts.TILES}, lambda r, row: r, mode, "de"
    )
    assert len(tiles.layout.annotations) == 16
    assert tiles.data[0].zmid == 100

    frame = pd.DataFrame({"x": ["a", "a", "b"], "y": [1, 2, 3], "s": ["p", "q", "p"]})
    spec = {"kind": "bar", "x": "x", "y": "y", "series": "s", "columns": ["x", "y", "s"],
            "rows": frame.to_numpy().tolist()}  # fmt: skip
    assert len(charts.agent_chart(spec, mode, "en").data) == 2
    too_many = {**spec, "rows": [[str(i), i, f"s{i}"] for i in range(5)]}
    assert charts.agent_chart(too_many, mode, "en") is None  # falls back to the table view


def _page_script(name: str, lang: str) -> None:
    import streamlit as st

    from schichtwechsel.ui import pages

    st.session_state.lang = lang
    getattr(pages, name)()


@pytest.mark.skipif(not WAREHOUSE.exists(), reason="needs a local warehouse")
@pytest.mark.parametrize("page", ["radar", "offers", "workforce", "assistant"])
@pytest.mark.parametrize("lang", ["de", "en"])
def test_pages_run(monkeypatch, page, lang):
    from streamlit.testing.v1 import AppTest

    from schichtwechsel.agent.dashboard import QUERIES
    from schichtwechsel.agent.executor import ReadOnlyMart
    from schichtwechsel.ui import pages

    def fake_dataset(name):
        mart = ReadOnlyMart()
        try:
            body = mart.fetch(QUERIES[name])
        finally:
            mart.close()
        return pd.DataFrame(body["rows"], columns=body["columns"])

    monkeypatch.setattr(pages, "dataset", fake_dataset)
    app = AppTest.from_function(_page_script, args=(page, lang), default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    assert app.title[0].value


def test_shell_runs_without_api():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception, app.exception
