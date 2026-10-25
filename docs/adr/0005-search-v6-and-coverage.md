# 5. Search on v6, and what the BA does not cover

Date: 2026-10-25
Status: accepted

## Context

The first live run failed with `403 No match found for request` on `/pc/v4/jobs`. The gateway no longer routes v4 search. `/pc/v6/jobs` answers with the same client id, and `/pc/v4/jobdetails` still works.

v6 changed the payload: `ergebnisliste` instead of `stellenangebote`, `firma` instead of `arbeitgeber`, `referenznummer`, and a list of locations (`stellenlokationen`) instead of one `arbeitsort`. It also adds fields we want anyway: full-time and part-time flags, shift work, minijob, contract term, whether pay is stated.

The first full snapshot also showed three coverage issues:

- Müller posts almost nothing to the BA: two postings under "Müller Handels GmbH & Co. KG". Free text for "Müller" returns hundreds of unrelated firms, and "Müller Service GmbH", which looked plausible, turned out to be the Theo Müller dairy group once the posting texts were read.
- Lidl posts its Austrian vacancies on the BA as well.
- The API refuses any page above 100, so a single search returns at most 10,000 results.

## Decision

- Search on v6, keep details on v4. The normaliser reads v6 names first and falls back to v4, so raw files from either version can be re-parsed.
- Store the new working-time and contract fields as columns. They feed the hours and benefits comparison later.
- Competitors can be searched by exact employer name (`employers` in the config) instead of free text. Müller uses this.
- Keep only postings located in Germany (`search.countries`).
- Page cap raised to 100. A search that hits it logs a warning.

## Consequences

- Müller stays in the radar but is not comparable on volume. Its store hiring runs through its own career site. Any chart or agent answer about Müller has to say so. This is a known gap, not a bug.
- Lidl job postings (about 7,200) are below the 10,000 ceiling today. If a search ever hits it, split it by region (`wo`) rather than raising limits.
- The next undocumented change will break ingestion again. The test fixture now mirrors the v6 shape, and a v4-shaped test keeps the fallback honest.
