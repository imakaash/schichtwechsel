import pandas as pd
import pytest

from schichtwechsel.hris.generate import REGION_WAGE, Simulation

POPULATION = {region: 1_000_000 for region in REGION_WAGE}


def run(pressure=None, stores=80, seed=1):
    pressure = pressure or {region: 100.0 for region in REGION_WAGE}
    return Simulation(pressure, POPULATION, 15.0, 1180.0, n_stores=stores, seed=seed).run()


@pytest.fixture(scope="module")
def data():
    return run()


def test_same_seed_same_data():
    a, b = run(stores=10, seed=5), run(stores=10, seed=5)
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_no_gender_and_plausible_ranges(data):
    months = data["employee_months"]
    assert not {"gender", "sex", "name"} & set(months.columns)
    assert months["age"].between(16, 70).all()
    assert months["store_vacancy_rate"].between(0, 1).all()
    assert months.loc[months["contract_type"] == "minijob", "weekly_hours"].max() <= 9
    assert months.loc[months["contract_type"] == "apprentice", "hourly_wage"].isna().all()


def test_turnover_is_in_a_retail_range(data):
    months = data["employee_months"]
    yearly = (months["exit_type"] == "voluntary").mean() * 12
    assert 0.15 < yearly < 0.35
    by_contract = months.groupby("contract_type")["exit_type"].apply(
        lambda s: (s == "voluntary").mean()
    )
    assert by_contract["minijob"] > by_contract["part_time"] > by_contract["full_time"]


def test_exits_open_requisitions_except_apprentices(data):
    months = data["employee_months"]
    exits = months[months["exit_type"].notna() & (months["contract_type"] != "apprentice")]
    assert len(exits) == len(data["requisitions"])
    reqs = data["requisitions"]
    assert (reqs.loc[reqs["status"] == "filled", "days_to_fill"] >= 3).all()
    assert reqs.loc[reqs["status"] == "open", "filled_on"].isna().all()


def test_competitor_pressure_raises_attrition():
    regions = sorted(REGION_WAGE)
    pressure = {r: (200.0 if i % 2 else 50.0) for i, r in enumerate(regions)}
    months = run(pressure, stores=160, seed=3)["employee_months"]
    rate = months.groupby("pressure_index")["exit_type"].apply(lambda s: (s == "voluntary").mean())
    assert rate[200.0] > rate[50.0] * 1.4

    reqs = run(pressure, stores=160, seed=3)["requisitions"]
    reqs["pressure"] = reqs["region"].map(pressure)
    days = reqs.groupby("pressure")["days_to_fill"].median()
    assert days[200.0] > days[50.0]


def test_manager_change_is_tracked(data):
    months = data["employee_months"]
    changed = months["months_since_manager_change"].dropna()
    assert len(changed) > 0 and (changed >= 0).all()
