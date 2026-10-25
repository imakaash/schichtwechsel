"""Monthly attrition hazard on the synthetic HR panel.

One row per person and month; the label is a voluntary exit in that month.
This is a discrete-time survival model: a monthly hazard h gives the risk
of leaving within k months as 1 - (1 - h)^k when the inputs stay as they
are. Other exits (end of contract, retirement) count as "did not leave
voluntarily", the cause-specific view of competing risks.

The main model is a logistic regression without regularisation, so its
coefficients can be checked against the generator's true drivers. A
gradient-boosting model runs alongside as a challenger. Age is never an
input; it is used only to check calibration across age bands afterwards.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd
import shap
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from schichtwechsel.hris.generate import Drivers

# Settings are fixed in advance, not tuned, so there is no separate
# validation period: train on everything before TEST_START, test after.
TEST_START = date(2025, 10, 1)

NUMERIC = [
    "weekly_hours", "pay_ratio", "store_vacancy_rate", "log_pressure", "recent_manager_change",
    "fixed_term_ends_within_2m", "january", "late_summer", "urban",
]  # fmt: skip
CATEGORICAL = ["contract_type", "role", "size", "tenure_band"]
BASELINE = {
    "contract_type": "full_time",
    "role": "sales_associate",
    "size": "M",
    "tenure_band": "24-60",
}
TENURE_BANDS = ([-1, 5, 23, 60, 10_000], ["0-5", "6-23", "24-60", "60+"])
AGE_BANDS = ([0, 24, 34, 44, 54, 120], ["under 25", "25-34", "35-44", "45-54", "55+"])


def features(months: pd.DataFrame) -> pd.DataFrame:
    """Model inputs from hris.employee_months joined with hris.stores."""
    out = months.copy()
    month = pd.to_datetime(out["month"]).dt.month
    out["log_pressure"] = np.log(out["pressure_index"] / 100)
    out["recent_manager_change"] = (out["months_since_manager_change"].fillna(999) < 6).astype(int)
    out["january"] = (month == 1).astype(int)
    out["late_summer"] = month.isin([8, 9]).astype(int)
    out["tenure_band"] = pd.cut(
        out["tenure_months"], bins=TENURE_BANDS[0], labels=TENURE_BANDS[1]
    ).astype(str)
    for col in ("fixed_term_ends_within_2m", "urban"):
        out[col] = out[col].astype(int)
    out["y"] = (out["exit_type"] == "voluntary").astype(int)
    return out


def load_panel(wh) -> pd.DataFrame:
    return features(
        wh.query(
            """
            SELECT m.*, s.size, s.urban
            FROM hris.employee_months m JOIN hris.stores s USING (store_id)
            """
        )
    )


def split(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    month = pd.to_datetime(panel["month"]).dt.date
    return panel[month < TEST_START], panel[month >= TEST_START]


def logistic() -> Pipeline:
    encoder = OneHotEncoder(
        drop=[BASELINE[c] for c in CATEGORICAL], handle_unknown="ignore", sparse_output=False
    )
    return Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [("num", StandardScaler(), NUMERIC), ("cat", encoder, CATEGORICAL)],
                    verbose_feature_names_out=False,
                ),
            ),
            ("model", LogisticRegression(C=np.inf, max_iter=5000)),
        ]
    )


def boosting() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=400,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=200,
        l2_regularization=1.0,
        categorical_features="from_dtype",
        early_stopping=True,
        validation_fraction=0.15,
        random_state=0,
    )


def _boosting_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cols = frame[NUMERIC + CATEGORICAL].copy()
    for c in CATEGORICAL:
        cols[c] = cols[c].astype("category")
    return cols


def oracle(frame: pd.DataFrame, drivers: Drivers | None = None) -> np.ndarray:
    """The generator's true hazard without the hidden per-person effect, age left out.

    This is the best any model on these inputs can do; used for evaluation only.
    """
    d = drivers or Drivers()
    x = np.full(len(frame), d.base)
    x += (
        frame["contract_type"]
        .map({"minijob": d.minijob, "part_time": d.part_time, "apprentice": d.apprentice})
        .fillna(0)
        .to_numpy()
    )
    t = frame["tenure_months"].to_numpy()
    x += np.select([t < 6, t < 24, t > 60], [d.probation, d.early_tenure, d.long_tenure], 0)
    x += d.pay_ratio * (frame["pay_ratio"].to_numpy() - 1)
    x += d.manager_change * frame["recent_manager_change"].to_numpy()
    x += d.understaffing * frame["store_vacancy_rate"].to_numpy()
    x += d.pressure * frame["log_pressure"].to_numpy()
    x += d.fixed_term_ending * frame["fixed_term_ends_within_2m"].to_numpy()
    x += d.january * frame["january"].to_numpy() + d.late_summer * frame["late_summer"].to_numpy()
    return 1 / (1 + np.exp(-x))


def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "average_precision": round(float(average_precision_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 5),
        "mean_predicted": round(float(p.mean()), 4),
        "observed_rate": round(float(y.mean()), 4),
    }


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    decile = pd.qcut(p, bins, labels=False, duplicates="drop")
    return (
        pd.DataFrame({"bin": decile, "p": p, "y": y})
        .groupby("bin")
        .agg(predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size"))
        .reset_index()
    )


def by_age_band(frame: pd.DataFrame, p: np.ndarray) -> pd.DataFrame:
    band = pd.cut(frame["age"], bins=AGE_BANDS[0], labels=AGE_BANDS[1])
    out = (
        pd.DataFrame({"age_band": band.astype(str), "p": p, "y": frame["y"].to_numpy()})
        .groupby("age_band", sort=False)
        .agg(predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size"))
        .reindex(AGE_BANDS[1])
        .reset_index()
    )
    out["ratio"] = (out["predicted"] / out["observed"]).round(2)
    out["flag"] = ~out["ratio"].between(0.8, 1.25)
    return out


def recovered_effects(model: Pipeline) -> pd.DataFrame:
    """Estimated log-odds effects on the original scale, next to the true ones."""
    prep, lr = model.named_steps["prep"], model.named_steps["model"]
    names = prep.get_feature_names_out()
    coef = dict(zip(names, lr.coef_[0], strict=True))
    scale = dict(zip(NUMERIC, prep.named_transformers_["num"].scale_, strict=True))
    d = Drivers()
    rows = [
        ("contract_type_minijob", "minijob vs full time", d.minijob),
        ("contract_type_part_time", "part time vs full time", d.part_time),
        ("contract_type_apprentice", "apprentice vs full time", d.apprentice),
        ("tenure_band_0-5", "tenure 0-5 vs 24-60 months", d.probation),
        ("tenure_band_6-23", "tenure 6-23 vs 24-60 months", d.early_tenure),
        ("tenure_band_60+", "tenure 60+ vs 24-60 months", d.long_tenure),
        ("pay_ratio", "pay ratio, per unit", d.pay_ratio),
        ("log_pressure", "log competitor pressure, per unit", d.pressure),
        ("recent_manager_change", "manager changed in last 6 months", d.manager_change),
        ("store_vacancy_rate", "store vacancy rate, per unit", d.understaffing),
        ("fixed_term_ends_within_2m", "fixed term ends within 2 months", d.fixed_term_ending),
        ("january", "January", d.january),
        ("late_summer", "August, September", d.late_summer),
        ("weekly_hours", "weekly hours, per hour", 0.0),
        ("urban", "urban store", 0.0),
    ]
    return pd.DataFrame(
        [
            {
                "effect": label,
                "true": true,
                "estimated": round(coef[name] / scale.get(name, 1.0), 3),
            }
            for name, label, true in rows
        ]
    )


def drivers_shap(model: Pipeline, background: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    """Exact linear SHAP values per original feature (one-hot columns summed)."""
    prep, lr = model.named_steps["prep"], model.named_steps["model"]
    masker = shap.maskers.Independent(prep.transform(background), max_samples=len(background))
    explainer = shap.LinearExplainer(lr, masker)
    values = explainer.shap_values(prep.transform(frame))
    names = prep.get_feature_names_out()
    groups = [next((c for c in CATEGORICAL if n.startswith(f"{c}_")), n) for n in names]
    grouped = pd.DataFrame(values, columns=groups).T.groupby(level=0, sort=False).sum().T
    return grouped


@dataclass
class Result:
    trained_at: str
    train: str
    test: str
    test_rows: int
    logistic: dict
    boosting: dict
    oracle: dict
    three_month: dict


def three_month_check(test: pd.DataFrame, p: np.ndarray) -> dict[str, float]:
    """Risk of leaving within 3 months, scored at the first test month."""
    first = test["month"].min()
    start = test[test["month"] == first].assign(p=p[(test["month"] == first).to_numpy()])
    window = test[test["month"] <= sorted(test["month"].unique())[2]]
    left = set(window.loc[window["y"] == 1, "employee_id"])
    y = start["employee_id"].isin(left).astype(int).to_numpy()
    risk = 1 - (1 - start["p"].to_numpy()) ** 3
    return {"people": len(start), **metrics(y, risk)}


def train(wh) -> tuple[Result, dict[str, pd.DataFrame]]:
    panel = load_panel(wh)
    train_rows, test = split(panel)

    lr = logistic().fit(train_rows, train_rows["y"])
    gb = boosting().fit(_boosting_frame(train_rows), train_rows["y"])
    p_lr = lr.predict_proba(test)[:, 1]
    p_gb = gb.predict_proba(_boosting_frame(test))[:, 1]

    result = Result(
        trained_at=datetime.now().isoformat(timespec="seconds"),
        train=f"{pd.Timestamp(panel['month'].min()).date()} to {TEST_START} (exclusive)",
        test=f"{TEST_START} to {pd.Timestamp(panel['month'].max()).date()}",
        test_rows=len(test),
        logistic=metrics(test["y"].to_numpy(), p_lr),
        boosting=metrics(test["y"].to_numpy(), p_gb),
        oracle=metrics(test["y"].to_numpy(), oracle(test)),
        three_month=three_month_check(test, p_lr),
    )

    # score everyone active in the latest month
    latest = panel[panel["month"] == panel["month"].max()].copy()
    latest["hazard_1m"] = lr.predict_proba(latest)[:, 1]
    latest["risk_3m"] = 1 - (1 - latest["hazard_1m"]) ** 3
    contributions = drivers_shap(lr, train_rows.sample(2000, random_state=0), latest)
    top = contributions.apply(lambda r: r.sort_values(ascending=False).index[:3].tolist(), axis=1)
    latest["top_drivers"] = top.to_numpy()

    sample = test.sample(min(5000, len(test)), random_state=0)
    global_shap = drivers_shap(lr, train_rows.sample(2000, random_state=1), sample)
    drivers = (
        pd.DataFrame(
            {"feature": global_shap.columns, "mean_abs_shap": global_shap.abs().mean().to_numpy()}
        )
        .sort_values("mean_abs_shap", ascending=False)
        .round(4)
    )

    tables = {
        "attrition_scores": latest[
            [
                "month",
                "employee_id",
                "store_id",
                "region",
                "role",
                "contract_type",
                "hazard_1m",
                "risk_3m",
                "top_drivers",
            ]
        ],  # fmt: skip
        "attrition_drivers": drivers,
        "attrition_effects": recovered_effects(lr),
        "attrition_calibration": calibration(test["y"].to_numpy(), p_lr),
        "attrition_age_check": by_age_band(test, p_lr),
    }
    return result, tables


def save(wh, result: Result, tables: dict[str, pd.DataFrame]) -> None:
    wh.con.execute("CREATE SCHEMA IF NOT EXISTS hris")
    for name, frame in tables.items():
        wh.replace_table(f"hris.{name}", frame)
    wh.con.execute(
        """
        CREATE TABLE IF NOT EXISTS hris.model_runs (
            model VARCHAR, trained_at TIMESTAMP, result VARCHAR
        )
        """
    )
    wh.con.execute(
        "INSERT INTO hris.model_runs VALUES ('attrition', ?, ?)",
        [result.trained_at, json.dumps(asdict(result))],
    )
    rows = [
        {"model": f"attrition_{name}", "metric": metric, "value": value, "test_period": result.test}
        for name in ("logistic", "boosting", "oracle", "three_month")
        for metric, value in getattr(result, name).items()
    ]
    wh.replace_table("hris.model_metrics", pd.DataFrame(rows))
    wh.refresh_views()
