# 9. Analytics layer in a separate mart schema

Date: 2026-10-25
Status: accepted

## Context

Step 3 turns raw postings and extracted features into numbers an HR team can use: where competitors hire hardest, what they pay and offer, how they staff stores. The same numbers feed the dashboard and the analyst agent (step 5), and the agent must not be able to read anything else.

Raw counts mislead in two ways. Lidl has four times dm's postings but also more stores, and NRW has the most postings because it has the most people.

## Decision

- All analysis views live in the `mart` schema (`src/schichtwechsel/sql/mart.sql`). The agent's SQL guard will allow `mart.*` and nothing else. Views that report a share also report the n behind it.
- Reference data with a source and date for every number, in `config/reference/`: store counts per employer and population per Bundesland (Destatis 2024). Reloaded on every warehouse open.
- Hiring pressure: open postings of all tracked retailers per 100,000 inhabitants per Bundesland and role, plus an index where 100 is the national rate. Weekly values are averages over the days observed in that week.
- Size adjustment: postings and apprenticeship postings per 100 stores.
- Postings without extracted features still get a role and a track, from the BA occupation and title (`role_from_occupation`, `track_from_posting`). On the 315 postings that have both, the occupation rule agrees with the extracted role 91% of the time.
- Data quality: `mart.snapshot_health` flags a competitor that drops by more than 30% day on day or vanishes; `sw check` exits non-zero on either, so the daily job can fail loudly. `mart.coverage` shows how much of each employer every analysis can see.

## Known limits

- Kaufland publishes its apprenticeship postings (2,082 of them, 18 programmes) with no location. They count in employer totals but not in regional views; `mart.coverage` reports them.
- The BA working-time flags mean "offered", not "is". A dm posting is often flagged full time and part time at once. Shares of the two do not add up to one.
- Pay, benefits and tariff views only see postings with extracted text, about 60 per large employer until the backfill runs. Medians on fewer than ten postings are shown with their n and should not be quoted.
- The Lidl store count dates from 2022; it is the oldest figure in the reference table.
- `mart.publication_months` only knows postings we have seen, so older months are undercounted until history builds up.
- Müller's BA volume is not comparable (store hiring runs through its own site). The note travels with the data in `mart.coverage`.

## First results (snapshot 2026-10-25)

- Store-staff pressure is highest in Rheinland-Pfalz (index 138), Baden-Württemberg (134) and Saarland (130), lowest in Sachsen-Anhalt, Thüringen and Sachsen (about 50).
- Kaufland posts 661 jobs per 100 stores, mostly apprenticeships; Rossmann 44.
- dm states pay in 65% of postings, median 15.00 €/h, which is its advertised entry wage. Rossmann states pay in 46%, median 17.42 €/h. Aldi and Lidl almost never state an amount but always refer to the Tarifvertrag.
- Distinctive benefits: workwear at Rossmann (87%), free food and drinks at Aldi (92%) and dm (87%), paid overtime at Lidl (80%), early shift planning at dm and Budni (85%).
