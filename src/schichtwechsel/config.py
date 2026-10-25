from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
WAREHOUSE = DATA_DIR / "warehouse.duckdb"
CONFIG_FILE = ROOT / "config" / "competitors.yaml"
REFERENCE_DIR = ROOT / "config" / "reference"


class Competitor(BaseModel):
    key: str
    label: str
    segment: str
    query: str | None = None
    employers: list[str] = Field(default_factory=list)
    match: str
    note: str | None = None

    @cached_property
    def pattern(self) -> re.Pattern[str]:
        return re.compile(self.match, re.IGNORECASE)

    def owns(self, employer: str | None) -> bool:
        return bool(employer) and self.pattern.search(employer) is not None

    def searches(self) -> list[dict[str, Any]]:
        """Exact employer names when given, otherwise the free-text query."""
        if self.employers:
            return [{"arbeitgeber": name} for name in self.employers]
        if self.query:
            return [{"was": self.query}]
        raise ValueError(f"{self.key}: set either `query` or `employers`")


class SearchSettings(BaseModel):
    offer_types: list[int] = Field(default_factory=lambda: [1])
    page_size: int = 100
    max_pages: int = 100
    pause: float = 0.5
    countries: list[str] = Field(default_factory=lambda: ["DEUTSCHLAND"])

    def in_scope(self, country: str | None) -> bool:
        """Postings without a country are kept; foreign ones are dropped."""
        return not country or not self.countries or country.upper() in self.countries


class RadarConfig(BaseModel):
    competitors: list[Competitor]
    search: SearchSettings = Field(default_factory=SearchSettings)

    def select(self, keys: list[str] | None) -> list[Competitor]:
        if not keys:
            return self.competitors
        unknown = set(keys) - {c.key for c in self.competitors}
        if unknown:
            raise ValueError(f"unknown competitor key(s): {', '.join(sorted(unknown))}")
        return [c for c in self.competitors if c.key in keys]


def load_config(path: Path = CONFIG_FILE) -> RadarConfig:
    with path.open(encoding="utf-8") as fh:
        return RadarConfig.model_validate(yaml.safe_load(fh))
