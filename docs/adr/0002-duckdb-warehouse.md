# 2. DuckDB as the warehouse

Date: 2026-10-25
Status: accepted

## Context

The workload is analytical: a batch write once a day, then aggregations and time series queries. Expected size is well under a few GB. The app will run on Azure Container Apps, scaled to zero when idle.

Candidates: PostgreSQL (local Docker, Azure Flexible Server), Azure SQL Database free offer, DuckDB.

## Decision

DuckDB, stored as a single file.

- Columnar engine built for exactly this kind of query; window functions, `QUALIFY`, `arg_max` and date arithmetic are all there.
- No server, so nothing to run locally and nothing to pay for in the cloud.
- Reads Parquet natively, which keeps a path open to object storage later.

Azure SQL free offer was the main alternative. It gives 100,000 vCore seconds a month, but open connections and health probes keep a serverless database awake, which burns that allowance and adds cold start delays after auto-pause.

## Consequences

- One writer at a time. Fine for a daily batch job; the web app only reads.
- In the cloud the file needs a home (Blob Storage or baked into the image). Decided at deployment time.
- SQL stays standard enough to port to Postgres if the project ever needs concurrent writes.
