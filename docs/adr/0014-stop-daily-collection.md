# 14. Stop daily data collection

Date: 2026-11-06
Status: accepted. Changes the daily job in ADR 0012 and 0013.

## Context

The daily GitHub Actions job collected postings and extraction results from 2026-10-25 to 2026-11-05. Each run used Actions minutes and Anthropic batch credit, and the project is a portfolio piece rather than a service anyone relies on.

## Decision

- Remove the daily workflow. The last snapshot is 2026-11-05.
- The warehouse in the `data` release stays as it is; the app keeps reading it.
- CI on every push and the weekly evals remain.

## Consequences

- No running cost apart from the analyst, which is capped per day, and the weekly evals.
- The data no longer changes. Figures in the app, the README and the findings refer to the snapshots up to 2026-11-05.
- Time series stop at twelve days, so the posting-volume forecast stays deferred.
- Collection can be resumed by restoring `.github/workflows/daily.yml` from git history.
