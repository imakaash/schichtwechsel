-- One row per posting per day it was visible on the job board.
-- Appending snapshots (instead of overwriting) is what lets us measure
-- how long a vacancy stays open.
CREATE TABLE IF NOT EXISTS postings_snapshot (
    snapshot_date DATE      NOT NULL,
    competitor    VARCHAR   NOT NULL,
    offer_type    SMALLINT  NOT NULL,
    refnr         VARCHAR   NOT NULL,
    title         VARCHAR,
    occupation    VARCHAR,
    employer      VARCHAR,
    plz           VARCHAR,
    city          VARCHAR,
    region        VARCHAR,
    country       VARCHAR,
    lat           DOUBLE,
    lon           DOUBLE,
    location_count SMALLINT,
    published_on  DATE,
    first_published_on DATE,
    start_on      DATE,
    modified_at   TIMESTAMP,
    full_time     BOOLEAN,
    part_time     BOOLEAN,
    shift_work    BOOLEAN,
    minijob       BOOLEAN,
    career_changer_ok BOOLEAN,
    pay_info      VARCHAR,
    contract_term VARCHAR,
    external_url  VARCHAR,
    PRIMARY KEY (snapshot_date, competitor, refnr)
);

-- Lifecycle per posting, derived from the snapshots.
-- A posting that disappears between two runs counts as closed on its last
-- sighting. That is a proxy for time-to-fill, not the real thing: an ad can
-- also be pulled without a hire.
CREATE OR REPLACE VIEW posting_lifecycle AS
WITH bounds AS (
    SELECT max(snapshot_date) AS latest FROM postings_snapshot
)
SELECT
    s.competitor,
    s.refnr,
    any_value(s.offer_type)                     AS offer_type,
    arg_max(s.title, s.snapshot_date)           AS title,
    arg_max(s.occupation, s.snapshot_date)      AS occupation,
    arg_max(s.region, s.snapshot_date)          AS region,
    arg_max(s.city, s.snapshot_date)            AS city,
    coalesce(min(s.first_published_on), min(s.published_on)) AS published_on,
    min(s.snapshot_date)                        AS first_seen,
    max(s.snapshot_date)                        AS last_seen,
    count(*)                                    AS days_observed,
    max(s.snapshot_date) = any_value(b.latest)  AS is_open,
    max(s.snapshot_date) - coalesce(min(s.first_published_on), min(s.published_on), min(s.snapshot_date)) AS days_online
FROM postings_snapshot s
CROSS JOIN bounds b
GROUP BY s.competitor, s.refnr;

-- Full posting text, fetched once per posting from the details endpoint.
-- status: ok, no_text (posting has no description), gone (404 by the time
-- we asked).
CREATE TABLE IF NOT EXISTS posting_details (
    refnr         VARCHAR   PRIMARY KEY,
    competitor    VARCHAR   NOT NULL,
    fetched_at    TIMESTAMP NOT NULL,
    status        VARCHAR   NOT NULL,
    text_hash     VARCHAR,
    school_level  VARCHAR,
    temp_agency   BOOLEAN
);

-- One row per distinct text. Chains reuse the same ad across hundreds of
-- stores, so extraction runs per text, not per posting.
CREATE TABLE IF NOT EXISTS posting_texts (
    text_hash     VARCHAR   PRIMARY KEY,
    body          VARCHAR   NOT NULL,
    chars         INTEGER   NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_batches (
    batch_id          VARCHAR   PRIMARY KEY,
    extractor_version VARCHAR   NOT NULL,
    submitted_at      TIMESTAMP NOT NULL,
    requests          INTEGER   NOT NULL,
    collected_at      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS extraction_batch_items (
    batch_id      VARCHAR   NOT NULL,
    text_hash     VARCHAR   NOT NULL,
    PRIMARY KEY (batch_id, text_hash)
);

CREATE TABLE IF NOT EXISTS posting_features (
    text_hash             VARCHAR   NOT NULL,
    extractor_version     VARCHAR   NOT NULL,
    extracted_at          TIMESTAMP NOT NULL,
    role_family           VARCHAR,
    track                 VARCHAR,
    entry_requirement     VARCHAR,
    hours_min             DOUBLE,
    hours_max             DOUBLE,
    contract              VARCHAR,
    pay_min               DOUBLE,
    pay_max               DOUBLE,
    pay_period            VARCHAR,
    pay_evidence          VARCHAR,
    tariff                VARCHAR,
    staff_discount_pct    DOUBLE,
    vacation_days         INTEGER,
    benefits              VARCHAR[],
    german_level          VARCHAR,
    suspicious_text       BOOLEAN,
    input_tokens          INTEGER,
    output_tokens         INTEGER,
    PRIMARY KEY (text_hash, extractor_version)
);

-- Anything that did not make it into posting_features, with the reason.
-- Nothing is dropped silently: a text is retried once, then stays here
-- for review.
CREATE TABLE IF NOT EXISTS extraction_failures (
    text_hash         VARCHAR   NOT NULL,
    extractor_version VARCHAR   NOT NULL,
    batch_id          VARCHAR,
    failed_at         TIMESTAMP NOT NULL,
    reason            VARCHAR   NOT NULL,
    raw_output        VARCHAR
);

-- Features per posting for the newest extractor version.
CREATE OR REPLACE VIEW posting_features_current AS
SELECT d.refnr, d.competitor, d.school_level, d.temp_agency, f.*
FROM posting_details d
JOIN posting_features f USING (text_hash)
WHERE f.extractor_version = (SELECT max(extractor_version) FROM posting_features);
