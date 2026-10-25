"""Read-only access to the mart views for the analyst agent."""

from __future__ import annotations

import datetime as dt
import decimal
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from schichtwechsel.agent.guard import MAX_ROWS, SCHEMA, CheckedQuery, check
from schichtwechsel.config import WAREHOUSE

MIN_GROUP = 5

# One line per view for the model; columns come from the database itself.
VIEW_NOTES = {
    "postings_latest": "Every competitor posting open in the latest snapshot, with city, plz, "
    "lat/lon, role_family, track, and extracted fields where has_features is true. Public data.",
    "postings": "Same as postings_latest for every snapshot day. Use for history.",
    "open_postings_weekly": "Average open postings per day in a week, by competitor, region, role.",
    "hiring_pressure": "Open postings of all tracked retailers per 100,000 inhabitants by "
    "Bundesland and role, and pressure_index where 100 is the national rate. Excludes postings "
    "without a location.",
    "posting_flow": "New and disappeared postings per week and competitor. The first snapshot "
    "day is not counted as new.",
    "employer_scale": "Open postings and apprenticeship postings per 100 stores, with the store "
    "count, its date and segment.",
    "working_time": "Share of postings offering full time, part time, minijob, shift work. "
    "Flags mean 'offered', so shares do not add up to one.",
    "track_mix": "Share of postings per track (regular, apprenticeship, dual_study, side_job, "
    "seasonal_temp, internship) per competitor.",
    "apprenticeship_by_region": "Apprenticeship share of postings per competitor and region.",
    "pay_transparency": "Share of postings stating pay or a tariff reference, and median "
    "hourly and monthly pay, per competitor and track. Only postings with extracted text.",
    "benefits_matrix": "Share of postings naming each benefit, per competitor. Only postings "
    "with extracted text.",
    "posting_languages": "Postings by language of the posting text, per competitor.",
    "publication_months": "Postings by month of first publication. Older months undercounted.",
    "snapshot_health": "Data quality: postings per competitor per day and drop flags.",
    "coverage": "How much of each competitor's postings has a location, text and extracted "
    "features. The note column carries known limits (Müller).",
    "workforce_monthly": "The chain's own (synthetic) headcount and exits per month, region "
    "and contract type.",
    "time_to_fill_history": "The chain's openings per quarter, region and role: median and "
    "P80 days to fill, applicants.",
    "time_to_fill_outlook": "Expected median and P80 days to fill an opening posted next "
    "month, per region and opening type.",
    "time_to_fill_effects": "Estimated effects on log days to fill, next to the true ones.",
    "attrition_outlook": "Expected voluntary leavers in the next 3 months and average risk, "
    "per region and contract type, for the chain's current staff.",
    "attrition_by_store": "Expected voluntary leavers in the next 3 months per store.",
    "attrition_drivers": "Global importance of attrition drivers (mean absolute SHAP).",
    "attrition_calibration": "Attrition model calibration by decile on the test year.",
    "attrition_age_check": "Attrition model calibration by age band. Age is not a model input.",
    "model_quality": "Test metrics of the attrition and time-to-fill models.",
}
HR_VIEWS = {"workforce_monthly", "attrition_outlook", "attrition_by_store"}


@dataclass
class QueryResult:
    query_id: str
    sql: str
    purpose: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None

    def for_model(self) -> dict[str, Any]:
        if self.error:
            return {"query_id": self.query_id, "error": self.error}
        return {
            "query_id": self.query_id,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": len(self.rows),
            "truncated": self.truncated,
        }


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 4)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


class ReadOnlyMart:
    def __init__(self, path: Path = WAREHOUSE) -> None:
        self.con = duckdb.connect(
            str(path),
            read_only=True,
            config={"enable_external_access": False, "lock_configuration": True},
        )
        self.views = {
            row[0]
            for row in self.con.execute(
                "SELECT view_name FROM duckdb_views() WHERE schema_name = ?", [SCHEMA]
            ).fetchall()
        }

    def close(self) -> None:
        self.con.close()

    def catalog(self) -> str:
        """Views, columns and notes, as text for the system prompt."""
        columns: dict[str, list[str]] = {}
        for view, column, dtype in self.con.execute(
            """
            SELECT table_name, column_name, data_type FROM duckdb_columns()
            WHERE schema_name = ? ORDER BY table_name, column_index
            """,
            [SCHEMA],
        ).fetchall():
            columns.setdefault(view, []).append(f"{column} {dtype.lower()}")
        lines = []
        for view in sorted(self.views):
            note = VIEW_NOTES.get(view, "")
            lines.append(f"mart.{view}: {note}\n  columns: {', '.join(columns.get(view, []))}")
        return "\n".join(lines)

    def run(self, query_id: str, sql: str, purpose: str) -> QueryResult:
        result = QueryResult(query_id=query_id, sql=sql, purpose=purpose)
        try:
            checked: CheckedQuery = check(sql, self.views)
            cursor = self.con.execute(checked.sql)
            rows = cursor.fetchall()
            result.sql = checked.sql
            result.columns = [d[0] for d in cursor.description]
        except Exception as exc:  # guard errors and SQL errors both go back to the model
            result.error = str(exc).splitlines()[0]
            return result

        # second line of defence for the privacy rule; the HR views already drop small groups
        if checked.views & HR_VIEWS and "headcount" in result.columns:
            i = result.columns.index("headcount")
            if any(r[i] is not None and r[i] < MIN_GROUP for r in rows):
                result.error = f"result contains groups under {MIN_GROUP} people; aggregate further"
                return result

        result.truncated = len(rows) > MAX_ROWS
        result.rows = [[_plain(v) for v in row] for row in rows[:MAX_ROWS]]
        return result
