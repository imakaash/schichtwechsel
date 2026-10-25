-- Analytics layer. The dashboard and the analyst agent read only from the
-- mart schema; the agent's SQL guard allows nothing else. Every view that
-- reports a share also reports the n behind it.
CREATE SCHEMA IF NOT EXISTS mart;

-- Role family from the BA occupation, for postings without extracted
-- features. ADR 0009 has the agreement rate with the extracted value.
CREATE OR REPLACE MACRO role_from_occupation(occupation) AS
    CASE
        WHEN occupation IS NULL THEN 'other'
        WHEN regexp_matches(lower(occupation), 'filialleiter|verkaufsstellenleiter|verkaufsaufsicht|fachwirt/in - handel')
            THEN 'store_management'
        WHEN regexp_matches(lower(occupation), 'verkäufer|verkauf|drogist|einzelhandel|kassierer')
            THEN 'store_sales'
        WHEN regexp_matches(lower(occupation), 'lager|kommissionier|logisti|gabelstapler|transport')
            THEN 'logistics'
        WHEN regexp_matches(lower(occupation), 'kraftfahrer|fahrer')
            THEN 'driving'
        WHEN regexp_matches(lower(occupation), 'mechatroniker|elektroniker|techniker|maschinen|haustechn')
            THEN 'technical'
        WHEN regexp_matches(lower(occupation), 'reinigung|fleischer|bäck|nahrungsmittel')
            THEN 'other'
        ELSE 'head_office'
    END;

CREATE OR REPLACE MACRO track_from_posting(offer_type, title) AS
    CASE
        WHEN offer_type = 4 AND regexp_matches(lower(coalesce(title, '')), 'dual|studium|bachelor|b\.a\.')
            THEN 'dual_study'
        WHEN offer_type = 4 THEN 'apprenticeship'
        WHEN regexp_matches(lower(coalesce(title, '')), 'aushilfe|studentenjob|werkstudent|nebenjob')
            THEN 'side_job'
        ELSE 'regular'
    END;

-- One row per posting per snapshot day.
CREATE OR REPLACE VIEW mart.postings AS
SELECT
    s.snapshot_date,
    date_trunc('week', s.snapshot_date)::DATE                     AS week,
    s.competitor,
    c.segment,
    s.refnr,
    s.offer_type,
    s.title,
    s.occupation,
    s.region,
    s.city,
    s.plz,
    s.lat,
    s.lon,
    coalesce(s.first_published_on, s.published_on)               AS published_on,
    s.full_time,
    s.part_time,
    s.shift_work,
    s.minijob,
    coalesce(f.role_family, role_from_occupation(s.occupation))   AS role_family,
    coalesce(f.track, track_from_posting(s.offer_type, s.title))  AS track,
    f.text_hash IS NOT NULL                                       AS has_features,
    f.entry_requirement,
    f.contract,
    f.hours_min,
    f.hours_max,
    f.pay_min,
    f.pay_max,
    f.pay_period,
    f.tariff,
    f.staff_discount_pct,
    f.vacation_days,
    f.benefits,
    f.german_level,
    f.posting_language
FROM postings_snapshot s
LEFT JOIN ref_competitors c USING (competitor)
LEFT JOIN posting_features_current f ON f.refnr = s.refnr;

CREATE OR REPLACE VIEW mart.postings_latest AS
SELECT * FROM mart.postings
WHERE snapshot_date = (SELECT max(snapshot_date) FROM postings_snapshot);

-- Average open postings per day within a week. Dividing by the days we
-- observed that week (not the days a group appeared) keeps a posting seen
-- on one day of five from counting as a full week.
CREATE OR REPLACE VIEW mart.open_postings_weekly AS
WITH days AS (
    SELECT date_trunc('week', snapshot_date)::DATE AS week, count(DISTINCT snapshot_date) AS days
    FROM postings_snapshot
    GROUP BY 1
)
SELECT
    p.week,
    p.competitor,
    p.segment,
    p.region,
    p.role_family,
    count(*) / any_value(d.days)  AS avg_open_postings,
    any_value(d.days)             AS days_observed
FROM mart.postings p
JOIN days d USING (week)
GROUP BY p.week, p.competitor, p.segment, p.region, p.role_family;

-- Hiring pressure per Bundesland and role: open postings of all tracked
-- retailers per 100,000 inhabitants, and an index where 100 is the
-- national rate for that role and week. Postings without a location
-- (Kaufland publishes its apprenticeships nationwide) are left out here;
-- mart.coverage counts them.
CREATE OR REPLACE VIEW mart.hiring_pressure AS
WITH regional AS (
    SELECT
        week,
        region,
        role_family,
        sum(avg_open_postings)                                              AS open_postings,
        coalesce(sum(avg_open_postings) FILTER (WHERE segment = 'drugstore'), 0) AS drugstore_postings,
        coalesce(sum(avg_open_postings) FILTER (WHERE segment = 'grocery'), 0)   AS grocery_postings
    FROM mart.open_postings_weekly
    WHERE region IN (SELECT region FROM ref_population)
    GROUP BY week, region, role_family
),
national AS (
    SELECT week, role_family, sum(open_postings) / (SELECT sum(population) FROM ref_population) AS rate
    FROM regional
    GROUP BY week, role_family
)
SELECT
    r.week,
    r.region,
    p.name                                                      AS region_name,
    r.role_family,
    round(r.open_postings, 1)                                   AS open_postings,
    round(r.drugstore_postings, 1)                              AS drugstore_postings,
    round(r.grocery_postings, 1)                                AS grocery_postings,
    round(r.open_postings / p.population * 100000, 2)           AS per_100k_inhabitants,
    round(100 * (r.open_postings / p.population) / n.rate, 1)   AS pressure_index
FROM regional r
JOIN ref_population p USING (region)
JOIN national n USING (week, role_family);

-- Postings that appeared or disappeared, per week. The first snapshot day
-- is a backlog, not inflow, so it is not counted as new.
CREATE OR REPLACE VIEW mart.posting_flow AS
WITH bounds AS (
    SELECT min(snapshot_date) AS first_day, max(snapshot_date) AS last_day FROM postings_snapshot
),
events AS (
    SELECT date_trunc('week', first_seen)::DATE AS week, competitor, 1 AS new, 0 AS closed
    FROM posting_lifecycle, bounds
    WHERE first_seen > first_day
    UNION ALL
    -- gone before the latest snapshot: counted in the week it was last seen
    SELECT date_trunc('week', last_seen)::DATE, competitor, 0, 1
    FROM posting_lifecycle, bounds
    WHERE last_seen < last_day
)
SELECT week, competitor, sum(new)::BIGINT AS new_postings, sum(closed)::BIGINT AS closed_postings
FROM events
GROUP BY week, competitor;

-- Size-adjusted hiring per employer. Store counts and their sources are in
-- config/reference/store_counts.csv.
CREATE OR REPLACE VIEW mart.employer_scale AS
SELECT
    p.competitor,
    c.label,
    c.segment,
    count(*)                                                       AS open_postings,
    count(*) FILTER (WHERE p.offer_type = 4)                       AS apprenticeship_postings,
    s.stores_de,
    s.as_of                                                        AS stores_as_of,
    round(100.0 * count(*) / s.stores_de, 1)                       AS postings_per_100_stores,
    round(100.0 * count(*) FILTER (WHERE p.offer_type = 4) / s.stores_de, 1)
                                                                   AS apprenticeships_per_100_stores
FROM mart.postings_latest p
JOIN ref_competitors c USING (competitor)
LEFT JOIN ref_store_counts s USING (competitor)
GROUP BY p.competitor, c.label, c.segment, s.stores_de, s.as_of;

-- Working-time mix from the BA flags, available for every posting.
CREATE OR REPLACE VIEW mart.working_time AS
SELECT
    competitor,
    role_family,
    count(*)                                  AS postings,
    round(avg(full_time::INT), 3)             AS share_full_time,
    round(avg(part_time::INT), 3)             AS share_part_time,
    round(avg(minijob::INT), 3)               AS share_minijob,
    round(avg(shift_work::INT), 3)            AS share_shift_work
FROM mart.postings_latest
GROUP BY competitor, role_family;

CREATE OR REPLACE VIEW mart.track_mix AS
SELECT
    competitor,
    track,
    count(*)                                                          AS postings,
    round(count(*) / sum(count(*)) OVER (PARTITION BY competitor), 3) AS share
FROM mart.postings_latest
GROUP BY competitor, track;

CREATE OR REPLACE VIEW mart.apprenticeship_by_region AS
SELECT
    competitor,
    coalesce(region, '(no location)')                     AS region,
    count(*)                                              AS postings,
    count(*) FILTER (WHERE offer_type = 4)                AS apprenticeship_postings,
    round(avg((offer_type = 4)::INT), 3)                  AS share_apprenticeship
FROM mart.postings_latest
GROUP BY competitor, coalesce(region, '(no location)');

-- Pay and tariff references, from extracted features. Medians use the
-- midpoint of each stated range. Apprenticeship pay is monthly, most store
-- pay hourly, so the track stays in the grouping.
CREATE OR REPLACE VIEW mart.pay_transparency AS
SELECT
    competitor,
    track,
    count(*)                                                                 AS postings_with_text,
    round(avg((pay_min IS NOT NULL)::INT), 3)                                AS share_pay_stated,
    round(avg((tariff <> 'not_mentioned')::INT), 3)                          AS share_tariff_reference,
    count(*) FILTER (WHERE pay_period = 'hour')                              AS hourly_n,
    median((pay_min + pay_max) / 2) FILTER (WHERE pay_period = 'hour')       AS median_hourly_pay,
    min(pay_min) FILTER (WHERE pay_period = 'hour')                          AS min_hourly_pay,
    max(pay_max) FILTER (WHERE pay_period = 'hour')                          AS max_hourly_pay,
    count(*) FILTER (WHERE pay_period = 'month')                             AS monthly_n,
    median((pay_min + pay_max) / 2) FILTER (WHERE pay_period = 'month')      AS median_monthly_pay
FROM mart.postings_latest
WHERE has_features
GROUP BY competitor, track;

-- Share of postings naming each benefit, per employer.
CREATE OR REPLACE VIEW mart.benefits_matrix AS
WITH base AS (
    SELECT competitor, count(*) AS postings_with_text
    FROM mart.postings_latest WHERE has_features GROUP BY competitor
),
mentions AS (
    SELECT competitor, unnest(benefits) AS benefit
    FROM mart.postings_latest WHERE has_features
),
codes AS (SELECT DISTINCT benefit FROM mentions)
SELECT
    b.competitor,
    c.benefit,
    b.postings_with_text,
    count(m.benefit)                                      AS postings_mentioning,
    round(count(m.benefit) / b.postings_with_text, 3)     AS share
FROM base b
CROSS JOIN codes c
LEFT JOIN mentions m ON m.competitor = b.competitor AND m.benefit = c.benefit
GROUP BY b.competitor, c.benefit, b.postings_with_text;

CREATE OR REPLACE VIEW mart.posting_languages AS
SELECT competitor, posting_language, count(*) AS postings
FROM mart.postings_latest
WHERE has_features
GROUP BY competitor, posting_language;

-- Postings by month of first publication. Only postings we have seen are
-- in here, so older months are undercounted until history builds up.
CREATE OR REPLACE VIEW mart.publication_months AS
SELECT
    competitor,
    offer_type,
    date_trunc('month', published_on)::DATE   AS month,
    count(*)                                  AS postings
FROM posting_lifecycle
WHERE published_on IS NOT NULL
GROUP BY competitor, offer_type, date_trunc('month', published_on);

-- Data quality: rows per competitor per day, with a flag when a
-- competitor drops by more than 30 percent or disappears. A sudden drop
-- usually means the API or a filter changed, not the labour market.
CREATE OR REPLACE VIEW mart.snapshot_health AS
WITH grid AS (
    SELECT d.snapshot_date, c.competitor
    FROM (SELECT DISTINCT snapshot_date FROM postings_snapshot) d
    CROSS JOIN ref_competitors c
),
daily AS (
    SELECT g.snapshot_date, g.competitor, count(s.refnr) AS postings
    FROM grid g
    LEFT JOIN postings_snapshot s USING (snapshot_date, competitor)
    GROUP BY g.snapshot_date, g.competitor
),
lagged AS (
    SELECT *, lag(postings) OVER (PARTITION BY competitor ORDER BY snapshot_date) AS previous
    FROM daily
)
SELECT
    snapshot_date,
    competitor,
    postings,
    previous,
    round(100.0 * (postings - previous) / nullif(previous, 0), 1)   AS change_pct,
    CASE
        WHEN postings = 0 THEN 'empty'
        WHEN previous IS NOT NULL AND postings < 0.7 * previous THEN 'drop'
        ELSE 'ok'
    END                                                             AS status
FROM lagged;

-- How much of the latest snapshot each analysis can see.
CREATE OR REPLACE VIEW mart.coverage AS
SELECT
    p.competitor,
    count(*)                                              AS open_postings,
    count(*) FILTER (WHERE p.region IS NULL)              AS without_location,
    count(d.refnr) FILTER (WHERE d.status = 'ok')         AS with_text,
    count(*) FILTER (WHERE p.has_features)                AS with_features,
    round(avg(p.has_features::INT), 3)                    AS share_with_features,
    any_value(c.note)                                     AS note
FROM mart.postings_latest p
LEFT JOIN posting_details d ON d.refnr = p.refnr
LEFT JOIN ref_competitors c ON c.competitor = p.competitor
GROUP BY p.competitor;
