-- Time-to-fill outlook, created once the model has run. Rows are stores,
-- not people, so no small-group rule applies.

CREATE OR REPLACE VIEW mart.time_to_fill_outlook AS
SELECT * FROM hris.time_to_fill_outlook;

CREATE OR REPLACE VIEW mart.time_to_fill_effects AS
SELECT * FROM hris.time_to_fill_effects;
