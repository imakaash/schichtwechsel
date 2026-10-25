# 1. Job postings come from the BA Jobsuche

Date: 2026-10-25
Status: accepted

## Context

We need competitor hiring data for at least seven retailers, daily, with location and job type. Options:

1. Scrape each company's career site
2. Use a commercial job board (StepStone, Indeed)
3. Use the job search of the Bundesagentur für Arbeit (BA)

## Decision

Use the BA Jobsuche.

- One source covers every employer, so comparisons are apples to apples.
- Results are already structured: occupation, location with coordinates, publication date, contract type.
- Apprenticeships are a separate offer type (`angebotsart=4`). Apprentice hiring is a large share of store staffing, so this matters.
- Seven career-site scrapers would mean seven parsers that break independently, plus terms-of-use questions. Commercial boards prohibit scraping and have no free API.

## Consequences

- The API is undocumented. If it changes, ingestion breaks. Raw responses are stored so we can re-parse without re-fetching.
- Not every posting reaches the BA. Counts are a consistent sample, not a census. Fine for trends and comparisons, not for absolute headcount claims.
- Search is by free text, so results contain noise (other employers matching the term). Each competitor has a regex on the employer name; `sw discover` shows what gets dropped.
