-- Workforce views over the synthetic HR data. Created only once the hris
-- tables exist. Individual rows never leave the hris schema: every view
-- here is an aggregate, and groups of fewer than 5 people are dropped, so
-- no single person can be read off a small group.

CREATE OR REPLACE VIEW mart.workforce_monthly AS
SELECT
    month,
    region,
    contract_type,
    count(*)                                              AS headcount,
    count(*) FILTER (WHERE exit_type = 'voluntary')       AS voluntary_exits,
    count(*) FILTER (WHERE exit_type IS NOT NULL)         AS all_exits,
    round(count(*) FILTER (WHERE exit_type = 'voluntary') / count(*), 4) AS voluntary_exit_rate
FROM hris.employee_months
GROUP BY month, region, contract_type
HAVING count(*) >= 5;

CREATE OR REPLACE VIEW mart.time_to_fill_history AS
SELECT
    date_trunc('quarter', opened_on)::DATE                AS quarter,
    region,
    role,
    count(*)                                              AS openings,
    count(*) FILTER (WHERE status = 'open')               AS still_open,
    median(days_to_fill)                                  AS median_days_to_fill,
    quantile_cont(days_to_fill, 0.8)                      AS p80_days_to_fill,
    median(applicants)                                    AS median_applicants
FROM hris.requisitions
GROUP BY 1, region, role
HAVING count(*) >= 5;
