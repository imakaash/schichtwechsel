# 6. Extract posting fields with Haiku through the Batch API

Date: 2026-10-25
Status: accepted

## Context

Search results give occupation, place and a few flags. Pay, weekly hours, benefits, contract type and entry requirements are only in the free text. We need them for tens of thousands of postings, with daily increments of a few hundred to a few thousand.

A sample of postings from all seven employers shows how much the wording varies for the same fact ("mind. 15,00 Euro bis 19,83 Euro" vs. "übertariflicher Mindesteinstiegslohn von 15 € pro Stunde" vs. "Vergütung nach Tarif"). Regex rules would need constant upkeep per employer.

## Decision

- Claude Haiku 5.5 at low effort. The task is reading, not reasoning; a larger model costs more without a measurable gain on this schema. The labelled test set (plan step 2.5) is where that claim gets checked.
- Message Batches API: half price, and nothing here is latency sensitive. `sw extract one <refnr>` sends the same request directly for trying out prompt changes.
- Structured outputs with a JSON schema generated from the Pydantic model, so the response always parses. Bounds the API cannot enforce (hours, discount, plausible pay per period) are checked after parsing.
- Extraction runs per distinct text, not per posting. Texts are hashed after fetching; chains reuse one ad across many stores, so this cuts requests substantially.
- Results carry an `extractor_version`. Changing the model, prompt or schema means a new version and a re-run, never an in-place update.

## Consequences

- Cost is small: about 2,000 input and a few hundred output tokens per text, a few dollars for a full backfill at batch prices.
- Batches can take up to 24 hours. The daily pipeline submits and collects in separate steps.
- Details need one request per posting against a public API. The fetch is capped per competitor and runs newest first, so the backfill is spread over several days.
