"""Fixed queries behind the dashboard pages.

The UI asks for these by name; it cannot send SQL. All of them read the
mart schema only, through the same read-only connection as the agent.
"""

from __future__ import annotations

LATEST_WEEK = "(SELECT max(week) FROM mart.hiring_pressure)"

QUERIES = {
    "meta": """
        SELECT
            (SELECT max(snapshot_date) FROM mart.postings_latest) AS snapshot_date,
            (SELECT sum(open_postings) FROM mart.employer_scale) AS open_postings,
            (SELECT max(scored_month) FROM mart.attrition_outlook) AS scored_month
    """,
    "pressure": f"""
        SELECT region, region_name, role_family, open_postings, drugstore_postings,
               grocery_postings, per_100k_inhabitants, pressure_index
        FROM mart.hiring_pressure WHERE week = {LATEST_WEEK}
    """,
    "employer_scale": "SELECT * FROM mart.employer_scale",
    "working_time": """
        SELECT competitor, postings, share_part_time, share_minijob, share_full_time
        FROM mart.working_time WHERE role_family = 'store_sales'
    """,
    "coverage": "SELECT * FROM mart.coverage",
    "benefits": "SELECT * FROM mart.benefits_matrix",
    "pay": "SELECT * FROM mart.pay_transparency WHERE track IN ('regular', 'apprenticeship')",
    "attrition_outlook": "SELECT * FROM mart.attrition_outlook",
    "attrition_drivers": "SELECT * FROM mart.attrition_drivers",
    "turnover": """
        SELECT month, contract_type, sum(voluntary_exits) AS exits, sum(headcount) AS headcount,
               sum(voluntary_exits) / sum(headcount) AS rate
        FROM mart.workforce_monthly GROUP BY month, contract_type ORDER BY month
    """,
    "time_to_fill": "SELECT * FROM mart.time_to_fill_outlook",
    "model_quality": "SELECT * FROM mart.model_quality",
}
