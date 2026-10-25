# Model card: time to fill

`sw models time-to-fill` (`src/schichtwechsel/models/time_to_fill.py`). Trained on the **synthetic** requisitions described in [data-card.md](data-card.md).

## What it predicts

Days from opening a position to filling it, as a median and a P80: the day by which four in five comparable openings are filled. The model works on log days because waiting times are skewed; the P80 comes from the spread of its residuals.

## Inputs

Type of opening (sales associate, minijob, deputy, store manager), competitor hiring pressure in the Bundesland (real data), opened in November or December, urban store, store pay level relative to the market wage, store size.

## Evaluation

Train on openings before 2025-10, test on openings from 2025-10 to 2026-06 (826, all filled). Openings still open when the data ends (114, all from July 2026 on) have no fill date and are not used.

| Model | Median error | Mean error | R² on log days | Filled by P80 |
|---|---|---|---|---|
| Linear on log days | 9.0 days | 12.4 days | 0.24 | 80% |
| Gradient boosting | 9.2 days | 12.6 days | 0.21 | 79% |
| Ceiling (true drivers) | 9.1 days | 12.3 days | 0.24 | 81% |

The P80 is honest: four in five test openings were filled by it. R² is low because most of the spread is noise by design (sd 0.45 on log days); the true formula does no better. For planning, the P80 is the number to use, not the median.

## Do the effects match the truth?

| Effect on log days | True | Estimated |
|---|---|---|
| Competitor pressure, per unit of log index | 0.60 | 0.57 |
| Store manager vs sales associate | 0.60 | 0.62 |
| Deputy vs sales associate | 0.35 | 0.32 |
| Minijob vs sales associate | -0.15 | -0.17 |
| Opened in November or December | 0.20 | 0.22 |
| Urban store | -0.10 | -0.09 |
| Store pay level, per unit | -3.00 | -3.34 |
| Store size (no true effect) | 0 | -0.01, 0.00 |

## Outlook

`mart.time_to_fill_outlook` gives the expected median and P80 for an opening posted next month, averaged over each region's stores. For a sales associate: about 20 days (P80 30) in Sachsen against 37 days (P80 54) in Rheinland-Pfalz, driven mainly by competitor pressure.

## Limits

- Real requisition data would be censored throughout: openings cancelled, re-posted or filled internally. Here only the end of the data censors, and the test period avoids it. On real data this needs a survival model for time to fill, not a regression.
- Competitor pressure is a single snapshot per region, so the model cannot show how a rise in pressure would change waiting times over time.
