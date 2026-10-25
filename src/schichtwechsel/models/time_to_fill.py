"""Days to fill an opening, on the synthetic requisitions.

Waiting times are skewed, so the models predict log days. A linear model
on log days gives a median (exp of the prediction) and, from the spread of
its residuals, a P80: the day by which four in five openings like this are
filled. Gradient boosting runs as a challenger, as for attrition.

Openings still open when the data ends have no fill date. The test period
stops before those start, so no test opening is censored.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from schichtwechsel.hris.generate import Hiring
from schichtwechsel.models.common import store_metrics

TEST_START, TEST_END = date(2025, 10, 1), date(2026, 7, 1)
NUMERIC = ["log_pressure", "holiday_season", "urban", "pay_level"]
CATEGORICAL = ["opening", "size"]
BASELINE = {"opening": "sales_associate", "size": "M"}
Z80 = float(norm.ppf(0.8))


def features(reqs: pd.DataFrame) -> pd.DataFrame:
    out = reqs.copy()
    opened = pd.to_datetime(out["opened_on"])
    out["opening"] = np.where(out["contract_type"] == "minijob", "minijob", out["role"])
    out["log_pressure"] = np.log(out["pressure_index"] / 100)
    out["holiday_season"] = opened.dt.month.isin([11, 12]).astype(int)
    out["urban"] = out["urban"].astype(int)
    out["log_days"] = np.log(out["days_to_fill"])
    return out


def load(wh) -> pd.DataFrame:
    market = json.loads(wh.scalar("SELECT inputs FROM hris.generation"))["market_hourly"]
    reqs = wh.query(
        """
        SELECT r.*, s.size, s.urban, s.wage_offset / ? AS pay_level, p.pressure_index
        FROM hris.requisitions r
        JOIN hris.stores s ON s.store_id = r.store_id
        JOIN (SELECT DISTINCT region, pressure_index FROM hris.employee_months) p
            ON p.region = r.region
        """,
        [market],
    )
    return features(reqs)


def linear() -> Pipeline:
    encoder = OneHotEncoder(
        drop=[BASELINE[c] for c in CATEGORICAL], handle_unknown="ignore", sparse_output=False
    )
    return Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [("num", "passthrough", NUMERIC), ("cat", encoder, CATEGORICAL)],
                    verbose_feature_names_out=False,
                ),
            ),
            ("model", LinearRegression()),
        ]
    )


def boosting() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=300,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=40,
        categorical_features="from_dtype",
        early_stopping=True,
        random_state=0,
    )


def _boosting_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cols = frame[NUMERIC + CATEGORICAL].copy()
    for c in CATEGORICAL:
        cols[c] = cols[c].astype("category")
    return cols


def oracle(frame: pd.DataFrame, hiring: Hiring | None = None) -> np.ndarray:
    """True expected log days without noise; evaluation only."""
    h = hiring or Hiring()
    return (
        h.days_base
        + h.days_pressure * frame["log_pressure"].to_numpy()
        + frame["opening"].map(h.days_role).to_numpy()
        + h.days_season * frame["holiday_season"].to_numpy()
        + h.days_urban * frame["urban"].to_numpy()
        + h.days_pay * frame["pay_level"].to_numpy()
    )


def metrics(log_days: np.ndarray, mu: np.ndarray, sigma: float) -> dict[str, float]:
    days, median = np.exp(log_days), np.exp(mu)
    return {
        "median_abs_error_days": round(float(np.median(np.abs(days - median))), 2),
        "mean_abs_error_days": round(float(np.mean(np.abs(days - median))), 2),
        "r2_log_days": round(float(1 - np.var(log_days - mu) / np.var(log_days)), 4),
        "p80_coverage": round(float(np.mean(log_days <= mu + Z80 * sigma)), 4),
    }


def recovered_effects(model: Pipeline) -> pd.DataFrame:
    prep, lr = model.named_steps["prep"], model.named_steps["model"]
    coef = dict(zip(prep.get_feature_names_out(), lr.coef_, strict=True))
    h = Hiring()
    rows = [
        ("log_pressure", "log competitor pressure, per unit", h.days_pressure),
        ("opening_minijob", "minijob vs sales associate", h.days_role["minijob"]),
        ("opening_deputy_manager", "deputy vs sales associate", h.days_role["deputy_manager"]),
        ("opening_store_manager", "store manager vs sales associate", h.days_role["store_manager"]),
        ("holiday_season", "opened in November or December", h.days_season),
        ("urban", "urban store", h.days_urban),
        ("pay_level", "store pay level, per unit", h.days_pay),
        ("size_S", "small vs medium store", 0.0),
        ("size_L", "large vs medium store", 0.0),
    ]
    return pd.DataFrame(
        [{"effect": label, "true": t, "estimated": round(coef[n], 3)} for n, label, t in rows]
    )


@dataclass
class Result:
    trained_at: str
    train: str
    test: str
    test_openings: int
    linear: dict
    boosting: dict
    oracle: dict


def train(wh) -> tuple[Result, dict[str, pd.DataFrame]]:
    reqs = load(wh)
    opened = pd.to_datetime(reqs["opened_on"]).dt.date
    filled = reqs[reqs["status"] == "filled"]
    train_rows = filled[opened[filled.index] < TEST_START]
    test = filled[(opened[filled.index] >= TEST_START) & (opened[filled.index] < TEST_END)]

    lin = linear().fit(train_rows, train_rows["log_days"])
    sigma = float(np.std(train_rows["log_days"] - lin.predict(train_rows)))
    gb = boosting().fit(_boosting_frame(train_rows), train_rows["log_days"])
    gb_sigma = float(np.std(train_rows["log_days"] - gb.predict(_boosting_frame(train_rows))))

    y = test["log_days"].to_numpy()
    result = Result(
        trained_at=datetime.now().isoformat(timespec="seconds"),
        train=f"opened before {TEST_START}",
        test=f"opened {TEST_START} to {TEST_END} (exclusive)",
        test_openings=len(test),
        linear=metrics(y, lin.predict(test), sigma),
        boosting=metrics(y, gb.predict(_boosting_frame(test)), gb_sigma),
        oracle=metrics(y, oracle(test), Hiring().days_sd),
    )

    # outlook: an opening posted next month, in each store, averaged per region and opening type
    stores = wh.query(
        """
        SELECT s.store_id, s.region, s.size, s.urban, s.wage_offset, p.pressure_index
        FROM hris.stores s
        JOIN (SELECT DISTINCT region, pressure_index FROM hris.employee_months) p USING (region)
        """
    )
    market = json.loads(wh.scalar("SELECT inputs FROM hris.generation"))["market_hourly"]
    next_month = pd.Timestamp(wh.scalar("SELECT max(month) FROM hris.employee_months"))
    next_month = (next_month + pd.offsets.MonthBegin(1)).date()
    grid = stores.merge(pd.DataFrame({"opening": list(Hiring().days_role)}), how="cross")
    grid = grid.assign(
        pay_level=grid["wage_offset"] / market,
        log_pressure=np.log(grid["pressure_index"] / 100),
        holiday_season=int(next_month.month in (11, 12)),
        urban=grid["urban"].astype(int),
    )
    grid["mu"] = lin.predict(grid)
    outlook = (
        grid.groupby(["region", "opening"])
        .agg(
            stores=("store_id", "size"),
            mu=("mu", "mean"),
            pressure_index=("pressure_index", "first"),
        )
        .reset_index()
    )
    outlook["opened_in"] = next_month
    outlook["median_days"] = np.exp(outlook["mu"]).round(0)
    outlook["p80_days"] = np.exp(outlook["mu"] + Z80 * sigma).round(0)
    outlook = outlook.drop(columns="mu")

    tables = {
        "time_to_fill_outlook": outlook,
        "time_to_fill_effects": recovered_effects(lin),
    }
    return result, tables


def save(wh, result: Result, tables: dict[str, pd.DataFrame]) -> None:
    for name, frame in tables.items():
        wh.replace_table(f"hris.{name}", frame)
    wh.con.execute(
        "CREATE TABLE IF NOT EXISTS hris.model_runs "
        "(model VARCHAR, trained_at TIMESTAMP, result VARCHAR)"
    )
    wh.con.execute(
        "INSERT INTO hris.model_runs VALUES ('time_to_fill', ?, ?)",
        [result.trained_at, json.dumps(asdict(result))],
    )
    rows = [
        {
            "model": f"time_to_fill_{name}",
            "metric": metric,
            "value": value,
            "test_period": result.test,
        }
        for name in ("linear", "boosting", "oracle")
        for metric, value in getattr(result, name).items()
    ]
    store_metrics(wh, "time_to_fill", rows)
    wh.refresh_views()
