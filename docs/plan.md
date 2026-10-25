# Plan

Status as of 2026-10-25. Steps 2 to 7 take roughly five weeks part-time; steps 4 and 5 are the largest.

## 1. Ingestion and storage (done)

- Daily pull of postings for 7 competitors from the BA Jobsuche (search on v6, details on v4).
- Employer and country filters, page cap of 100.
- Raw payloads in `data/raw/`, DuckDB table with one row per posting per day.
- `posting_lifecycle` view: first seen, last seen, days online, still open.
- CLI: `sw discover`, `sw snapshot`, `sw profile`. Tests and ADRs 0001 to 0005.
- Ongoing: run `sw snapshot` daily so a time series builds up (automated in step 6).

## 2. LLM extraction with guardrails (in progress)

Done: details fetch with text dedupe, schema, prompt, batch submit and collect, plausibility and pay grounding checks, retry and failure tracking, extractor v3, 50 tuning labels and 30 holdout labels (ADRs 0006 to 0008). Holdout: 90 to 100% on most fields, 77% on entry_requirement. Open: full backfill of posting texts and extraction.

1. Fetch the full posting text from the details endpoint, only for postings not seen before.
2. Pydantic schema for the extracted fields: role family, weekly hours, contract type, pay range and unit, benefits as fixed codes (staff discount, holiday pay, bike leasing, company pension, ...), Ausbildung vs. experienced hire vs. career changer, required language level.
3. Extraction with Haiku through the Batch API. No tools in that call; posting text is wrapped and treated as untrusted input.
4. Validate every output against the schema. Failures are retried once, then set aside for review, never dropped silently.
5. Hand-label about 50 postings as a test set and measure accuracy per field.
6. Store results in `posting_features`, keyed by posting number and extraction version.
7. ADRs: model choice and batching, injection threat model.

## 3. Analytics layer (SQL) (done, ADR 0009)

1. Views for the hiring-pressure index per region, role and week; share of postings that state pay and pay ranges per competitor; benefits matrix; Ausbildung share and seasonality.
2. Normalise posting counts by store count per competitor, from a small documented reference table.
3. Data-quality checks: daily row counts, alerts on sudden drops (an early sign of API changes), coverage note for Müller.

## 4. Synthetic HRIS and models (in progress)

Done: synthetic HR data and data card; attrition model with model card. Open: time-to-fill model; posting-volume forecast deferred until about eight weeks of snapshots exist.

1. Generate synthetic employees, stores, applicants and monthly snapshot tables. Drivers: tenure, hours, contract, store size, region, manager changes, pay relative to the market.
2. Real competitor hiring pressure from step 3 feeds the simulated attrition. This links internal and external data.
3. Data card documenting how the data was generated.
4. Models: attrition as a survival model with time-aware validation, time-to-fill forecast per region and role, posting-volume forecast per competitor.
5. SHAP explanations, model card, calibration check.
6. Model outputs stored as tables the agent can query.

## 5. Bilingual HR analyst agent

1. FastAPI backend with a plain tool-use loop on the Anthropic SDK (Sonnet).
2. Tools: `run_sql`, `forecast`, `make_chart`, `explain_risk`.
3. Guardrails:
   - SQL guard: parsed with sqlglot, SELECT only, allowlisted views, row limit.
   - Privacy: no individual employee rows, groups smaller than 5 suppressed.
   - Grounding: every number in an answer must appear in the tool results.
   - Topic and language: off-topic requests refused, answers follow the UI language.
4. About 40 golden questions in German and English, checking numbers, refusals and language. Runs in CI.
5. Logging of tool calls, tokens and cost per question.

## 6. UI, deployment and automation

1. Streamlit UI in its own container. UI text in `de.json` and `en.json`, data in canonical codes. Pages: competitor radar (map and trends), benefits comparison, workforce risk, agent chat.
2. Own palette and typography, no default theme.
3. Docker images for API and UI, pushed to GitHub Container Registry.
4. Azure Container Apps with scale to zero, API key as a secret.
5. GitHub Actions: daily cron for snapshot, incremental extraction and data upload; a second workflow for tests, evals and deploy.
6. DuckDB/Parquet data in Azure Blob Storage or a mounted file share, inside the free tier.

## 7. Presentation

1. README in German and English, architecture diagram, model card, data card.
2. Short write-up of findings, for example dm's part-time and minijob share against the others.
3. Two-minute demo video in German.
4. Push to GitHub under your own name with a clean history.

## Open decisions

- Below Bundesland level (district or 50 km radius) for questions like "Raum Karlsruhe". Coordinates are already stored.
- Müller coverage: accept and document the gap, or add a small compliant check of its career site. Current lean: accept the gap.
- Azure account type: standard free account or Azure for Students.
