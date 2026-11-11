# 15. Switch off the analyst and the weekly evals

Date: 2026-11-11
Status: accepted. Changes ADR 0011 and 0013.

## Context

After daily collection stopped (ADR 0014), the remaining API cost came from Claude Sonnet: the analyst in the web app and the weekly golden-question run on GitHub Actions.

## Decision

- Switch the analyst off in the web app. The page stays and explains that it is off; `ASSISTANT_ON` in `src/schichtwechsel/ui/pages.py` turns it back on.
- Remove the evals workflow and the Anthropic key from the GitHub secrets.
- The agent code, its guardrails and the golden questions stay. `sw ask` and `sw eval` still run locally with a key in `.env`.

## Consequences

- No Sonnet calls from the deployed app or from GitHub.
- The 40 of 40 result is from the last run on 2026-11-09 and is no longer checked automatically.
