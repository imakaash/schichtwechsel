"""Synthetic HR data for a fictional drugstore chain.

Nothing here describes real people or a real employer. The chain has
stores in every Bundesland; employees leave month by month with a hazard
built from the documented coefficients in `Drivers` plus unobserved
per-person noise. Two inputs are real: competitor hiring pressure per
Bundesland and the market wage from competitor postings (both from the
mart schema). docs/data-card.md describes the whole design.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np
import pandas as pd

START = date(2023, 1, 1)
END = date(2026, 9, 1)  # last monthly snapshot
MARKET_AS_OF = date(2026, 10, 1)  # the postings the market wage comes from
WAGE_GROWTH = 0.03  # per year; wages and the market move together

SIZES = {"S": 8, "M": 14, "L": 22}
SIZE_SHARES = {"S": 0.35, "M": 0.45, "L": 0.20}
APPRENTICE_SLOTS = {"S": 1, "M": 2, "L": 3}
ROLE_PAY = {"sales_associate": 1.0, "deputy_manager": 1.2, "store_manager": 1.6}
APPRENTICE_YEAR_PAY = (0.93, 1.0, 1.08)  # relative to the market median, year 1 to 3

# Synthetic regional wage level relative to the national market wage.
# The postings give one national figure; this spread is an assumption.
REGION_WAGE = {
    "BADEN_WUERTTEMBERG": 1.03, "BAYERN": 1.03, "HESSEN": 1.02, "HAMBURG": 1.04,
    "BERLIN": 1.02, "BREMEN": 1.01, "NORDRHEIN_WESTFALEN": 1.0, "RHEINLAND_PFALZ": 1.0,
    "SAARLAND": 0.99, "NIEDERSACHSEN": 0.99, "SCHLESWIG_HOLSTEIN": 0.99,
    "BRANDENBURG": 0.96, "SACHSEN": 0.95, "SACHSEN_ANHALT": 0.95, "THUERINGEN": 0.95,
    "MECKLENBURG_VORPOMMERN": 0.95,
}  # fmt: skip
CITY_STATES = {"BERLIN", "HAMBURG", "BREMEN"}


@dataclass(frozen=True)
class Drivers:
    """True effects on the monthly log-odds of a voluntary exit."""

    base: float = -4.7
    minijob: float = 1.0
    part_time: float = 0.25
    apprentice: float = -1.0
    probation: float = 0.9  # tenure under 6 months
    early_tenure: float = 0.35  # 6 to 24 months
    long_tenure: float = -0.45  # over 60 months
    young: float = 0.45  # under 25
    senior: float = -0.3  # 55 and over
    pay_ratio: float = -4.0  # per unit of (own wage / market wage - 1)
    manager_change: float = 0.6  # store manager changed in the last 6 months
    understaffing: float = 2.5  # per unit of store vacancy rate
    pressure: float = 0.8  # per unit of log(pressure index / 100)
    fixed_term_ending: float = 0.5  # contract ends in the next 1 or 2 months
    january: float = 0.3
    late_summer: float = 0.2  # August, September
    frailty_sd: float = 0.5  # unobserved, per person


@dataclass(frozen=True)
class Hiring:
    """True effects on log days to fill an opening and log applicant counts."""

    days_base: float = math.log(32)
    days_pressure: float = 0.6
    days_role: dict = field(
        default_factory=lambda: {
            "sales_associate": 0.0,
            "minijob": -0.15,
            "deputy_manager": 0.35,
            "store_manager": 0.6,
        }  # fmt: skip
    )
    days_season: float = 0.2  # opened in November or December
    days_urban: float = -0.1
    days_pay: float = -3.0  # per unit of (store wage level / market - 1)
    days_sd: float = 0.45
    applicants_base: float = math.log(14)
    applicants_pressure: float = -0.7
    applicants_pay: float = 2.0
    involuntary_monthly: float = 0.003
    apprentice_retention: float = 0.55  # stay on after the final exam
    fixed_term_share: float = 0.4  # of new non-apprentice hires
    fixed_term_conversion: float = 0.8


@dataclass
class Employee:
    employee_id: str
    store_id: str
    role: str
    contract: str
    hours: float
    hired: date
    birth_year: int
    frailty: float
    wage_offset: float  # personal deviation, euro per hour
    fixed_term_end: date | None = None
    apprentice_end: date | None = None
    exit_month: date | None = None
    exit_type: str | None = None


def months(start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


class Simulation:
    def __init__(
        self,
        pressure: dict[str, float],
        population: dict[str, int],
        market_hourly: float,
        market_apprentice: float,
        n_stores: int = 300,
        seed: int = 2026,
        drivers: Drivers | None = None,
        hiring: Hiring | None = None,
    ) -> None:
        self.rng = np.random.default_rng(seed)
        self.pressure = pressure
        self.market_hourly = market_hourly
        self.market_apprentice = market_apprentice
        self.d = drivers or Drivers()
        self.h = hiring or Hiring()
        self.stores = self._stores(population, n_stores)
        self.store = {s.store_id: s for s in self.stores.itertuples()}
        self.manager_changed: dict[str, date] = {}
        self.employees: dict[str, Employee] = {}
        self.rows: list[dict] = []
        self.requisitions: list[dict] = []
        self.pending: list[tuple[date, dict]] = []  # (start month, requisition)
        self._next_id = 0

    # setup -------------------------------------------------------------

    def _stores(self, population: dict[str, int], n: int) -> pd.DataFrame:
        regions = sorted(population)
        weights = np.array([population[r] for r in regions], dtype=float)
        quota = weights / weights.sum() * n
        counts = np.floor(quota).astype(int)
        for i in np.argsort(quota - counts)[::-1][: n - counts.sum()]:
            counts[i] += 1  # largest remainder
        rows = []
        for region, count in zip(regions, counts, strict=True):
            for _ in range(count):
                size = self.rng.choice(list(SIZE_SHARES), p=list(SIZE_SHARES.values()))
                urban = region in CITY_STATES or self.rng.random() < 0.5
                rows.append(
                    {
                        "store_id": f"F{len(rows) + 1:03d}",
                        "region": region,
                        "urban": bool(urban),
                        "size": size,
                        "planned_headcount": SIZES[size],
                        "wage_offset": round(float(self.rng.normal(0, 0.35)), 2),
                        "opened_year": int(self.rng.integers(1985, 2022)),
                    }
                )
        return pd.DataFrame(rows)

    def _market(self, month: date) -> float:
        return (1 + WAGE_GROWTH) ** (months_between(MARKET_AS_OF, month) / 12)

    def _new_id(self) -> str:
        self._next_id += 1
        return f"E{self._next_id:05d}"

    def _age(self, contract: str, role: str) -> int:
        r = self.rng
        if contract == "apprentice":
            return int(r.integers(16, 23))
        if role == "store_manager":
            return int(r.integers(28, 61))
        if contract == "minijob":
            group = r.choice(3, p=[0.5, 0.3, 0.2])  # students, mid career, retirees
            return int(r.integers(*[(18, 26), (26, 60), (60, 70)][group]))
        return int(np.clip(r.normal(38, 11), 18, 64))

    def _hire(self, store_id: str, role: str, contract: str, month: date, tenure: int = 0) -> None:
        r = self.rng
        hired = add_months(month, -tenure)
        hours = {
            "full_time": float(r.choice([38.0, 39.0, 40.0])),
            "part_time": float(r.integers(15, 31)),
            "minijob": float(r.choice([7.0, 8.0, 9.0])),
            "apprentice": 39.0,
        }[contract]
        e = Employee(
            employee_id=self._new_id(),
            store_id=store_id,
            role=role,
            contract=contract,
            hours=hours,
            hired=hired,
            birth_year=month.year - self._age(contract, role),
            frailty=float(r.normal(0, self.d.frailty_sd)),
            wage_offset=float(r.normal(0, 0.3)),
        )
        if contract == "apprentice":
            e.apprentice_end = add_months(hired, 36)
        elif tenure == 0 and r.random() < self.h.fixed_term_share:
            e.fixed_term_end = add_months(hired, int(r.choice([12, 24])))
        self.employees[e.employee_id] = e

    def _initial_workforce(self) -> None:
        r = self.rng
        for store in self.stores.itertuples():
            slots = APPRENTICE_SLOTS[store.size]
            rest = store.planned_headcount - 2 - slots
            full = round(rest * 0.25)
            part = round(rest * 0.45)
            plan = (
                [("store_manager", "full_time"), ("deputy_manager", "full_time")]
                + [("apprentice", "apprentice")] * slots
                + [("sales_associate", "full_time")] * full
                + [("sales_associate", "part_time")] * part
                + [("sales_associate", "minijob")] * (rest - full - part)
            )
            for role, contract in plan:
                if contract == "apprentice":
                    tenure = int(r.integers(0, 36))
                else:
                    mean = 18 if contract == "minijob" else 48
                    tenure = int(min(r.exponential(mean), 300))
                self._hire(store.store_id, role, contract, START, tenure)

    # monthly step ------------------------------------------------------

    def _hourly_wage(self, e: Employee, month: date, region: str, store_offset: float) -> float:
        level = self.market_hourly * REGION_WAGE[region] * self._market(month)
        tenure_years = months_between(e.hired, month) / 12
        return level * ROLE_PAY[e.role] + store_offset + e.wage_offset + 0.2 * min(tenure_years, 10)

    def _pay_ratio(self, e: Employee, month: date, store) -> tuple[float | None, float]:
        if e.contract == "apprentice":
            year = min(months_between(e.hired, month) // 12, 2)
            market = self.market_apprentice * APPRENTICE_YEAR_PAY[year] * self._market(month)
            pay = market * (1 + store.wage_offset / self.market_hourly)
            return None, pay / market
        wage = self._hourly_wage(e, month, store.region, store.wage_offset)
        market = (
            self.market_hourly * REGION_WAGE[store.region] * self._market(month) * ROLE_PAY[e.role]
        )
        return wage, wage / market

    def _hazard(self, row: dict, e: Employee) -> float:
        d = self.d
        x = d.base + e.frailty
        x += {"minijob": d.minijob, "part_time": d.part_time, "apprentice": d.apprentice}.get(
            e.contract, 0.0
        )
        t = row["tenure_months"]
        x += d.probation if t < 6 else d.early_tenure if t < 24 else d.long_tenure if t > 60 else 0
        x += d.young if row["age"] < 25 else d.senior if row["age"] >= 55 else 0
        x += d.pay_ratio * (row["pay_ratio"] - 1)
        msc = row["months_since_manager_change"]
        x += d.manager_change if msc is not None and msc < 6 else 0
        x += d.understaffing * row["store_vacancy_rate"]
        x += d.pressure * math.log(row["pressure_index"] / 100)
        x += d.fixed_term_ending if row["fixed_term_ends_within_2m"] else 0
        x += d.january if row["month"].month == 1 else 0
        x += d.late_summer if row["month"].month in (8, 9) else 0
        return 1 / (1 + math.exp(-x))

    def _open_requisition(self, e: Employee, month: date) -> None:
        r, h = self.rng, self.h
        store = self.store[e.store_id]
        pressure = math.log(self.pressure[store.region] / 100)
        key = "minijob" if e.contract == "minijob" else e.role
        pay_level = store.wage_offset / self.market_hourly
        opened = date(month.year, month.month, int(r.integers(1, 29)))
        log_days = (
            h.days_base
            + h.days_pressure * pressure
            + h.days_role[key]
            + (h.days_season if opened.month in (11, 12) else 0)
            + (h.days_urban if store.urban else 0)
            + h.days_pay * pay_level
            + r.normal(0, h.days_sd)
        )
        days = max(3, round(math.exp(log_days)))
        applicants = int(
            r.poisson(
                math.exp(
                    h.applicants_base
                    + h.applicants_pressure * pressure
                    + h.applicants_pay * pay_level
                )
                * (0.4 if e.role == "store_manager" else 0.6 if e.role == "deputy_manager" else 1.0)
            )
        )
        filled = pd.Timestamp(opened) + pd.Timedelta(days=days)
        req = {
            "requisition_id": f"R{len(self.requisitions) + 1:05d}",
            "store_id": e.store_id,
            "region": store.region,
            "role": e.role,
            "contract_type": e.contract,
            "opened_on": opened,
            "filled_on": filled.date(),
            "days_to_fill": days,
            "applicants": applicants,
        }
        self.requisitions.append(req)
        start = add_months(date(filled.year, filled.month, 1), 1)
        self.pending.append((start, req))

    def _vacancy_rates(self, month: date) -> dict[str, float]:
        open_count: dict[str, int] = {}
        for start, req in self.pending:
            if req["opened_on"] < month < start:
                open_count[req["store_id"]] = open_count.get(req["store_id"], 0) + 1
        return {
            s.store_id: open_count.get(s.store_id, 0) / s.planned_headcount
            for s in self.stores.itertuples()
        }

    def _step(self, month: date) -> None:
        r, h = self.rng, self.h

        # openings filled last month start now
        still = []
        for start, req in self.pending:
            if start <= month:
                if req["role"] == "store_manager":
                    self.manager_changed[req["store_id"]] = month
                self._hire(req["store_id"], req["role"], req["contract_type"], month)
            else:
                still.append((start, req))
        self.pending = still

        if month.month == 8:  # new apprentice cohort
            have: dict[str, int] = {}
            for e in self.employees.values():
                if e.contract == "apprentice" and e.exit_month is None:
                    have[e.store_id] = have.get(e.store_id, 0) + 1
            for store in self.store.values():
                for _ in range(APPRENTICE_SLOTS[store.size] - have.get(store.store_id, 0)):
                    self._hire(store.store_id, "apprentice", "apprentice", month)

        vacancy = self._vacancy_rates(month)
        for e in list(self.employees.values()):
            if e.exit_month is not None or e.hired > month:
                continue
            store = self.store[e.store_id]
            wage, ratio = self._pay_ratio(e, month, store)
            changed = self.manager_changed.get(e.store_id)
            row = {
                "month": month,
                "employee_id": e.employee_id,
                "store_id": e.store_id,
                "region": store.region,
                "role": e.role,
                "contract_type": e.contract,
                "weekly_hours": e.hours,
                "hourly_wage": None if wage is None else round(wage, 2),
                "pay_ratio": round(ratio, 4),
                "tenure_months": months_between(e.hired, month),
                "age": month.year - e.birth_year,
                "fixed_term": e.fixed_term_end is not None,
                "fixed_term_ends_within_2m": e.fixed_term_end is not None
                and 0 < months_between(month, e.fixed_term_end) <= 2,
                "months_since_manager_change": None
                if changed is None
                else months_between(changed, month),
                "store_vacancy_rate": round(vacancy[e.store_id], 4),
                "pressure_index": self.pressure[store.region],
                "exit_type": None,
            }

            exit_type = None
            if e.apprentice_end is not None and month >= e.apprentice_end:
                if r.random() < h.apprentice_retention:
                    e.contract, e.role, e.apprentice_end = "full_time", "sales_associate", None
                else:
                    exit_type = "apprenticeship_end"
            elif e.fixed_term_end is not None and month >= e.fixed_term_end:
                if r.random() < h.fixed_term_conversion:
                    e.fixed_term_end = None
                else:
                    exit_type = "contract_end"
            elif row["age"] >= 66:
                exit_type = "retirement"
            elif r.random() < self._hazard(row, e):
                exit_type = "voluntary"
            elif r.random() < h.involuntary_monthly:
                exit_type = "involuntary"

            if exit_type:
                row["exit_type"] = exit_type
                e.exit_month, e.exit_type = month, exit_type
                if e.contract != "apprentice":
                    self._open_requisition(e, month)
            self.rows.append(row)

    def run(self) -> dict[str, pd.DataFrame]:
        self._initial_workforce()
        for month in months(START, END):
            self._step(month)
        employees = pd.DataFrame(
            [
                {
                    "employee_id": e.employee_id,
                    "store_id": e.store_id,
                    "hired_on": e.hired,
                    "birth_year": e.birth_year,
                    "exit_month": e.exit_month,
                    "exit_type": e.exit_type,
                }
                for e in self.employees.values()
            ]
        )
        return {
            "stores": self.stores,
            "employees": employees,
            "employee_months": pd.DataFrame(self.rows),
            "requisitions": _hide_future(pd.DataFrame(self.requisitions)),
        }


def _hide_future(reqs: pd.DataFrame) -> pd.DataFrame:
    """An opening filled after the data ends is still open as far as the HR system knows."""
    cutoff = add_months(END, 1)
    still_open = pd.to_datetime(reqs["filled_on"]) >= pd.Timestamp(cutoff)
    reqs = reqs.copy()
    reqs["status"] = np.where(still_open, "open", "filled")
    reqs.loc[still_open, ["filled_on", "days_to_fill"]] = None
    return reqs


def truth() -> dict[str, float | dict]:
    """The coefficients the data was generated with, for the data card and model checks."""
    return {"drivers": asdict(Drivers()), "hiring": asdict(Hiring())}


def real_inputs(wh) -> dict:
    """Competitor pressure and market pay from the mart schema."""
    pressure = dict(
        wh.query(
            """
            SELECT region, pressure_index FROM mart.hiring_pressure
            WHERE role_family = 'store_sales'
              AND week = (SELECT max(week) FROM mart.hiring_pressure)
            """
        ).itertuples(index=False, name=None)
    )
    pay = wh.query(
        """
        SELECT
            median((pay_min + pay_max) / 2) FILTER (WHERE pay_period = 'hour' AND track = 'regular')
                AS hourly,
            count(*) FILTER (WHERE pay_period = 'hour' AND track = 'regular') AS hourly_n,
            median((pay_min + pay_max) / 2)
                FILTER (WHERE pay_period = 'month' AND track = 'apprenticeship') AS apprentice,
            count(*) FILTER (WHERE pay_period = 'month' AND track = 'apprenticeship')
                AS apprentice_n
        FROM mart.postings_latest
        WHERE has_features AND segment = 'drugstore'
        """
    ).iloc[0]
    population = dict(
        wh.query("SELECT region, population FROM ref_population").itertuples(index=False, name=None)
    )
    missing = set(population) - set(pressure)
    if missing:
        raise ValueError(f"no pressure index for {sorted(missing)}; run sw snapshot first")
    return {
        "pressure": pressure,
        "population": population,
        "market_hourly": float(pay["hourly"]),
        "market_hourly_n": int(pay["hourly_n"]),
        "market_apprentice": float(pay["apprentice"]),
        "market_apprentice_n": int(pay["apprentice_n"]),
    }


def generate(wh, seed: int = 2026, n_stores: int = 300) -> dict[str, int]:
    """Build the synthetic HR tables in the hris schema, replacing earlier ones."""
    import json
    from datetime import datetime

    inputs = real_inputs(wh)
    tables = Simulation(
        inputs["pressure"],
        inputs["population"],
        inputs["market_hourly"],
        inputs["market_apprentice"],
        n_stores=n_stores,
        seed=seed,
    ).run()
    tables["generation"] = pd.DataFrame(
        [
            {
                "generated_at": datetime.now(),
                "seed": seed,
                "inputs": json.dumps(inputs, ensure_ascii=False),
                "truth": json.dumps(truth()),
            }
        ]
    )
    wh.con.execute("CREATE SCHEMA IF NOT EXISTS hris")
    for name, frame in tables.items():
        wh.replace_table(f"hris.{name}", frame)
    wh.refresh_views()
    return {name: len(frame) for name, frame in tables.items()}
