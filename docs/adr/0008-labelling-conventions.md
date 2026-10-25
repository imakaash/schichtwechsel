# 8. Labelling conventions and the first three extractor versions

Date: 2026-10-25
Status: accepted

## Context

50 postings, sampled across all seven retailers, were labelled by hand without seeing model output. Comparing the first extractor run with these labels showed three kinds of disagreement: model errors, a label error, and places where the written definitions and the labeller's reading differed. The third kind has no right answer until someone decides it.

## Decision

Conventions, binding for labels and prompt alike:

- "beherrscht die deutsche Sprache" and similar phrasing is `fluent`.
- `side_job` is a job presented as Aushilfe, Studentenjob, Werkstudent or Nebenjob. A Minijob or few hours alone is `regular`; minijob status is a separate column from the BA data.
- `seasonal_temp` is help for a named season or period, such as Weihnachtsaushilfe.
- A reference to the duration of the Befristung means `fixed_term`. No statement at all means `not_stated`.
- Pay is base pay. Supplements and allowances are not pay, but Zuschläge still count as the `shift_premiums` benefit.
- `paid_overtime` needs overtime pay or compensation to be stated; minute-exact time tracking alone is not enough.
- Apprenticeships and dual study have entry requirement `none` unless they ask for finished vocational training.

Engineering changes found along the way:

- A failed pay check drops the pay fields and records why (`pay_rejected`), instead of discarding the whole row.
- The verbatim check on pay quotes ignores list markers and line breaks.

## Results on the 50 labelled postings

| Field | v1 | v2 | v3 |
|---|---|---|---|
| role_family | 94% | 92% | 94% |
| track | 92% | 80% | 98% |
| entry_requirement | 78% | 86% | 90% |
| hours | 98% | 94% | 100% |
| contract | 86% | 88% | 94% |
| pay (min, max, period) | 96% | 92% | 98% |
| tariff | 90% | 94% | 100% |
| staff discount, vacation days | 98% | 94% | 100% |
| german_level | 90% | 92% | 100% |
| benefits precision / recall | 96% / 95% | 96% / 89% | 100% / 97% |
| texts failed | 1 | 3 | 0 |

v2 shows why each change needs a re-run: a broad `side_job` definition and the pay rule leaked into other fields.

## Consequences

- These numbers are optimistic. The prompt was tuned against the same 50 postings it is scored on. Final accuracy is measured on a fresh labelled set that the prompt never saw.
- Three full runs over 123 texts cost about 15 cents.
- 5 of 123 postings are not in German (Bulgarian, Hungarian, Romanian), all warehouse jobs. Worth tracking as a recruiting signal.
