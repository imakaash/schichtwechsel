# 3. Store daily snapshots, not just the latest state

Date: 2026-10-25
Status: accepted

## Context

The API only shows postings that are online right now. When a posting disappears, the API does not say so. If we only kept the latest state, we could never tell how long a vacancy stayed open.

## Decision

Append one row per posting per day (`postings_snapshot`, key: date, competitor, refnr). Derive the lifecycle of each posting in a view (`posting_lifecycle`): first seen, last seen, days online, still open.

Re-running a day replaces that day's rows for that competitor, so runs are idempotent.

## Consequences

- Gives a time-to-fill proxy and a history of hiring demand, the basis for forecasting later.
- "Disappeared" is not "filled". A posting can be withdrawn or re-posted under a new number. The view says so in a comment and the analysis has to treat it as a proxy.
- Storage grows linearly with days. At a few thousand postings per day this stays small for years.
- Missed days create gaps. The ingestion job will run on a schedule so gaps are rare and visible.
