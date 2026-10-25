import json

import pytest

from schichtwechsel.hris.generate import REGION_WAGE, Simulation, _hide_future
from schichtwechsel.models import time_to_fill
from schichtwechsel.storage import Warehouse

PRESSURE = {r: (160.0 if i % 2 else 60.0) for i, r in enumerate(sorted(REGION_WAGE))}


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    tables = Simulation(
        PRESSURE, {r: 1_000_000 for r in REGION_WAGE}, 15.0, 1180.0, n_stores=250, seed=21
    ).run()
    with Warehouse(tmp_path_factory.mktemp("wh") / "wh.duckdb") as wh:
        wh.con.execute("CREATE SCHEMA IF NOT EXISTS hris")
        for name, frame in tables.items():
            wh.replace_table(f"hris.{name}", frame)
        wh.replace_table(
            "hris.generation",
            __import__("pandas").DataFrame([{"inputs": json.dumps({"market_hourly": 15.0})}]),
        )
        result, outputs = time_to_fill.train(wh)
        time_to_fill.save(wh, result, outputs)
        outlook = wh.query("SELECT * FROM mart.time_to_fill_outlook")
        yield result, outputs, outlook


def test_openings_after_the_data_ends_are_still_open():
    import pandas as pd

    reqs = pd.DataFrame(
        {"filled_on": [pd.Timestamp("2026-09-20").date(), pd.Timestamp("2026-10-03").date()],
         "days_to_fill": [10, 40]}
    )  # fmt: skip
    out = _hide_future(reqs)
    assert out["status"].tolist() == ["filled", "open"]
    assert out["days_to_fill"].isna().tolist() == [False, True]


def test_model_is_calibrated_and_recovers_effects(trained):
    result, outputs, _ = trained
    assert result.linear["p80_coverage"] == pytest.approx(0.8, abs=0.06)
    assert result.linear["median_abs_error_days"] < result.oracle["median_abs_error_days"] * 1.15
    effects = outputs["time_to_fill_effects"].set_index("effect")
    assert effects.loc["log competitor pressure, per unit", "estimated"] == pytest.approx(
        0.6, abs=0.25
    )
    assert effects.loc["store manager vs sales associate", "estimated"] > 0.3


def test_outlook_is_slower_under_pressure(trained):
    _, _, outlook = trained
    sales = outlook[outlook["opening"] == "sales_associate"].set_index("region")
    high = sales[sales["pressure_index"] == 160.0]["median_days"].mean()
    low = sales[sales["pressure_index"] == 60.0]["median_days"].mean()
    assert high > low
    assert (outlook["p80_days"] >= outlook["median_days"]).all()
