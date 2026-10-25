-- Model outputs, aggregated. Created once the attrition model has run.

CREATE OR REPLACE VIEW mart.attrition_outlook AS
SELECT
    month                                                 AS scored_month,
    region,
    contract_type,
    count(*)                                              AS headcount,
    round(sum(risk_3m), 1)                                AS expected_leavers_3m,
    round(avg(risk_3m), 4)                                AS avg_risk_3m
FROM hris.attrition_scores
GROUP BY month, region, contract_type
HAVING count(*) >= 5;

CREATE OR REPLACE VIEW mart.attrition_by_store AS
SELECT
    a.month                                               AS scored_month,
    a.store_id,
    a.region,
    s.size,
    count(*)                                              AS headcount,
    round(sum(a.risk_3m), 1)                              AS expected_leavers_3m,
    round(avg(a.risk_3m), 4)                              AS avg_risk_3m
FROM hris.attrition_scores a
JOIN hris.stores s USING (store_id)
GROUP BY a.month, a.store_id, a.region, s.size
HAVING count(*) >= 5;

CREATE OR REPLACE VIEW mart.attrition_drivers AS
SELECT * FROM hris.attrition_drivers;

CREATE OR REPLACE VIEW mart.attrition_calibration AS
SELECT * FROM hris.attrition_calibration;

CREATE OR REPLACE VIEW mart.attrition_age_check AS
SELECT * FROM hris.attrition_age_check;

CREATE OR REPLACE VIEW mart.model_quality AS
SELECT * FROM hris.model_metrics;
