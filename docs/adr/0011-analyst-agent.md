# 11. Analyst agent: plain tool loop with layered guardrails

Date: 2026-10-25
Status: accepted

## Context

HR staff should be able to ask questions in German or English ("Wo ist der Druck auf Filialpersonal am höchsten, und wie lange dauert dort eine Besetzung?") and get figures they can rely on. A language model writing SQL over HR data raises four risks: wrong numbers, exposure of individuals, side effects on the data, and instructions smuggled in through data or the question.

## Decision

**Loop.** A plain tool-use loop on the Anthropic SDK (`src/schichtwechsel/agent/loop.py`), no agent framework, so every step is visible and testable. Claude Sonnet 5.5, adaptive thinking at effort `medium`, server-side refusal fallback enabled. The conversation is append-only: assistant turns, including thinking blocks, go back unchanged. Rules and view catalog are one cached system block; the answer language sits after the cache breakpoint.

**Tools.** Three: `run_sql`, `make_chart` (only from an earlier query's rows), and `decline` with a fixed reason (off_topic, individual_data, write_request, unsupported_data). Declining through a tool makes refusals testable instead of a matter of matching phrases. Forecast and risk explanations are views (`time_to_fill_outlook`, `attrition_drivers`), not separate tools.

**Guardrails, each independent of the others:**

| Layer | What it stops |
|---|---|
| SQL guard (sqlglot): one SELECT, only `mart.*` views, no table functions, no file, catalog or environment functions, row cap 200 | Writes, reading `hris` or raw tables, reading files or secrets |
| Read-only DuckDB connection with external access off and configuration locked | The same, even if the guard had a gap |
| `mart` views aggregate HR data and drop groups under 5; a result check refuses HR results with headcount under 5 | Exposure of individuals |
| Grounding check: every figure in the answer must match a query value (rounding, German and English formats, percent allowed); one retry with feedback, then a fallback answer | Invented or remembered figures, unchecked arithmetic |
| Language check on the answer | Answers in the wrong language |
| Prompt: tool results are third-party data | Instructions inside posting titles |
| Golden questions (`evals/questions.yaml`), expected values computed by SQL at eval time | Regressions in any of the above |

**Logging.** Every question writes one line to `data/logs/agent.jsonl`: queries with their SQL, checks, decline reason, tokens including cache reads and writes, cost, duration.

## Results (2026-10-25)

40 golden questions, 20 German and 20 English: 24 with figures, 10 that must be declined (off topic, individual employees, write and export requests, an injection attempt, data that does not exist), 4 where the question and the answer language differ, 2 that need a caveat (Müller's coverage, Aldi not stating pay).

- First run: 37 of 40. Two failures were mistakes in the eval itself (an ambiguous question about apprenticeships versus dual study; an expected value rounded more than the answer). One was a real false positive: the grounding check rejected "80 %" used to explain the P80. Method constants (80, 100, 100,000, 12) are now exempt.
- After the fixes, a full run: 40 of 40, 35 US cents for the whole suite, 4.5 s median per question. Typical question: about 8,300 tokens read from cache, under 900 uncached.
- Because two questions were fixed after seeing results, the suite is a regression test, not an unseen test set.

## Consequences

- Derived figures (differences, ratios) must be computed in SQL. Answers are slightly more rigid, and every number in them can be traced to a query.
- The grounding check exempts small whole numbers (up to 10), years and four method constants, so a wrong "3" or a real figure that happens to be 80 could slip through. Accepted: those are mostly counting words and method terms.
- Golden questions cost real API credit (about 35 cents per full run) and depend on the data of the day; they run on demand and on a schedule, not on every push.
- Sessions live in the API process. Restarting the API ends open conversations.
