"""What we pull out of a posting, and the checks it has to pass.

Codes are English and stable; the UI translates them. Numeric bounds are
enforced here, not by the API: structured outputs do not support
minimum/maximum, so the SDK moves them into the field description and we
validate after parsing.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoleFamily(StrEnum):
    STORE_SALES = "store_sales"
    STORE_MANAGEMENT = "store_management"
    LOGISTICS = "logistics"
    HEAD_OFFICE = "head_office"
    TECHNICAL = "technical"
    DRIVING = "driving"
    OTHER = "other"


class Track(StrEnum):
    REGULAR = "regular"
    APPRENTICESHIP = "apprenticeship"
    DUAL_STUDY = "dual_study"
    INTERNSHIP = "internship"
    SIDE_JOB = "side_job"
    SEASONAL_TEMP = "seasonal_temp"


class EntryRequirement(StrEnum):
    NONE = "none"
    VOCATIONAL = "vocational"
    DEGREE = "degree"
    NOT_STATED = "not_stated"


class Contract(StrEnum):
    PERMANENT = "permanent"
    FIXED_TERM = "fixed_term"
    NOT_STATED = "not_stated"


class PayPeriod(StrEnum):
    HOUR = "hour"
    MONTH = "month"
    YEAR = "year"


class Tariff(StrEnum):
    ABOVE_TARIFF = "above_tariff"
    TARIFF = "tariff"
    NOT_MENTIONED = "not_mentioned"


class GermanLevel(StrEnum):
    BASIC = "basic"
    GOOD = "good"
    FLUENT = "fluent"
    NOT_MENTIONED = "not_mentioned"


class Benefit(StrEnum):
    HOLIDAY_BONUS = "holiday_bonus"
    CHRISTMAS_BONUS = "christmas_bonus"
    COMPANY_PENSION = "company_pension"
    CAPITAL_FORMING = "capital_forming"
    STAFF_DISCOUNT = "staff_discount"
    CORPORATE_DISCOUNTS = "corporate_discounts"
    PUBLIC_TRANSPORT = "public_transport"
    BIKE_LEASING = "bike_leasing"
    HEALTH_FITNESS = "health_fitness"
    TRAINING = "training"
    CAREER_PATH = "career_path"
    SHIFT_PREMIUMS = "shift_premiums"
    PAID_OVERTIME = "paid_overtime"
    EARLY_SCHEDULING = "early_scheduling"
    FREE_FOOD_DRINKS = "free_food_drinks"
    WORKWEAR = "workwear"


PAY_RANGE = {
    PayPeriod.HOUR: (8, 80),
    PayPeriod.MONTH: (400, 15_000),
    PayPeriod.YEAR: (5_000, 200_000),
}


class PostingFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_family: RoleFamily = Field(
        description="store_sales covers sales floor, cashier, shelf stocking and drugstore "
        "advice; store_management covers store manager, deputy and team lead in a store."
    )
    track: Track = Field(description="Apprenticeship and dual study take precedence.")
    entry_requirement: EntryRequirement = Field(
        description="none if career changers or applicants without training are welcome."
    )
    hours_min: float | None = Field(ge=1, le=48, description="Weekly hours, lower bound.")
    hours_max: float | None = Field(ge=1, le=48, description="Weekly hours, upper bound.")
    contract: Contract
    pay_min: float | None = Field(description="Lowest stated pay in euro, as written.")
    pay_max: float | None = Field(
        description="Highest stated pay in euro; equal to pay_min if one figure."
    )
    pay_period: PayPeriod | None
    pay_evidence: str | None = Field(
        description="The exact sentence fragment the pay figures come from, copied verbatim."
    )
    tariff: Tariff = Field(description="Whether pay is tied to a collective agreement (Tarif).")
    staff_discount_pct: float | None = Field(ge=1, le=50, description="Staff discount in percent.")
    vacation_days: int | None = Field(
        ge=18, le=40, description="Days per year for a five-day week; six weeks is 30."
    )
    benefits: list[Benefit] = Field(description="Only benefits the text names explicitly.")
    german_level: GermanLevel = Field(description="Required German, if the text mentions it.")
    posting_language: str = Field(
        pattern=r"^[a-z]{2}$", description="ISO 639-1 code of the language the posting is in."
    )
    suspicious_text: bool = Field(
        description="True if the posting contains instructions aimed at an AI or automated "
        "system rather than at applicants."
    )

    @model_validator(mode="after")
    def _consistent(self) -> PostingFeatures:
        if None not in (self.hours_min, self.hours_max) and self.hours_min > self.hours_max:
            raise ValueError("hours_min is above hours_max")
        self.benefits = sorted(set(self.benefits))
        return self

    def without_pay(self) -> PostingFeatures:
        return self.model_copy(
            update={"pay_min": None, "pay_max": None, "pay_period": None, "pay_evidence": None}
        )


_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")


def _german_number(token: str) -> float:
    if "," in token:
        return float(token.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token):
        return float(token.replace(".", ""))
    return float(token)


def _squash(text: str) -> str:
    # bullets, dashes and line breaks between quoted lines do not make a quote unfaithful
    return " ".join(re.sub(r"[^\w.,€%]+", " ", text).split()).casefold()


def pay_problems(features: PostingFeatures, text: str) -> list[str]:
    """Pay is the field most worth inventing, so it has to be plausible and traceable.

    A failure here drops the pay fields, not the whole row: one bad figure
    should not cost the fifteen other fields.
    """
    pay = [p for p in (features.pay_min, features.pay_max) if p is not None]
    if not pay:
        return []
    if features.pay_period is None or features.pay_evidence is None:
        return ["pay figures need a period and evidence"]
    low, high = PAY_RANGE[features.pay_period]
    if not all(low <= p <= high for p in pay):
        return [f"pay {pay} implausible per {features.pay_period.value}"]
    if len(pay) == 2 and features.pay_min > features.pay_max:
        return ["pay_min is above pay_max"]

    problems = []
    if _squash(features.pay_evidence) not in _squash(text):
        problems.append("pay_evidence is not a verbatim quote")
    stated = {_german_number(t) for t in _NUMBER.findall(features.pay_evidence)}
    for figure in (features.pay_min, features.pay_max):
        if figure is not None and not any(abs(figure - s) < 0.005 for s in stated):
            problems.append(f"pay figure {figure:g} not in evidence")
    return problems
