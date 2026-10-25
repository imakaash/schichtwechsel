import pandas as pd
import pytest

from schichtwechsel.hris.generate import REGION_WAGE, Simulation
from schichtwechsel.models import attrition
from schichtwechsel.storage import Warehouse

PRESSURE = {r: (160.0 if i % 2 else 60.0) for i, r in enumerate(sorted(REGION_WAGE))}


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    tables = Simulation(
        PRESSURE, {r: 1_000_000 for r in REGION_WAGE}, 15.0, 1180.0, n_stores=200, seed=11
    ).run()
    with Warehouse(tmp_path_factory.mktemp("wh") / "wh.duckdb") as wh:
        wh.con.execute("CREATE SCHEMA IF NOT EXISTS hris")
        for name, frame in tables.items():
            wh.replace_table(f"hris.{name}", frame)
        result, outputs = attrition.train(wh)
        attrition.save(wh, result, outputs)
        views = {
            name: wh.query(f"SELECT * FROM mart.{name}")
            for name in (
                "attrition_outlook",
                "attrition_by_store",
                "workforce_monthly",
                "model_quality",
            )
        }
        yield result, outputs, views


def test_age_is_not_an_input():
    assert "age" not in attrition.NUMERIC + attrition.CATEGORICAL


def test_time_split_keeps_test_after_train():
    panel = pd.DataFrame({"month": pd.to_datetime(["2025-09-01", "2025-10-01", "2026-01-01"])})
    train, test = attrition.split(panel)
    assert train["month"].max() < test["month"].min()
    assert len(train) == 1 and len(test) == 2


def test_model_reaches_the_ceiling_and_recovers_drivers(trained):
    result, outputs, _ = trained
    assert result.logistic["roc_auc"] > result.oracle["roc_auc"] - 0.03
    effects = outputs["attrition_effects"].set_index("effect")
    assert effects.loc["pay ratio, per unit", "estimated"] == pytest.approx(-4.0, abs=1.5)
    assert effects.loc["log competitor pressure, per unit", "estimated"] == pytest.approx(
        0.8, abs=0.4
    )
    assert effects.loc["weekly hours, per hour", "estimated"] == pytest.approx(0, abs=0.05)


def test_scores_are_consistent(trained):
    _, outputs, _ = trained
    scores = outputs["attrition_scores"]
    assert (scores["risk_3m"] >= scores["hazard_1m"]).all()
    assert scores["month"].nunique() == 1
    assert scores["top_drivers"].map(len).eq(3).all()


def test_mart_views_hide_small_groups(trained):
    _, _, views = trained
    for name in ("attrition_outlook", "attrition_by_store", "workforce_monthly"):
        assert (views[name]["headcount"] >= 5).all(), name
    assert "employee_id" not in views["attrition_outlook"].columns
    assert set(views["model_quality"]["model"]) >= {"attrition_logistic", "attrition_oracle"}


def test_exit_rate_is_share_of_headcount(trained):
    _, _, views = trained
    w = views["workforce_monthly"]
    expected = w["voluntary_exits"] / w["headcount"]
    assert (w["voluntary_exit_rate"] - expected).abs().max() < 1e-4
    assert w["voluntary_exit_rate"].mean() < 0.05
