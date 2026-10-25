# Model card: monthly attrition risk

`sw models attrition` (`src/schichtwechsel/models/attrition.py`). Trained on the **synthetic** HR data described in [data-card.md](data-card.md); nothing here applies to a real workforce.

## What it predicts

The probability that an employee leaves **voluntarily** in a given month (the monthly hazard), and from it the risk of leaving within three months, 1 - (1 - h)^3, assuming inputs stay as they are. One row per person and month: a discrete-time survival model. Other exits (end of a fixed-term contract, end of an apprenticeship, retirement, dismissal) count as not voluntary.

## Inputs

Contract type, role, weekly hours, pay relative to the regional market wage, tenure band, whether a fixed-term contract ends in the next one or two months, whether the store manager changed in the last six months, store vacancy rate, competitor hiring pressure in the Bundesland (real data), January and late-summer flags, store size, urban or not.

**Not an input: age.** Age is a protected attribute under the AGG. It is used only to check calibration afterwards. No gender exists in the data.

## Models

| | Role |
|---|---|
| Logistic regression, unregularised | Main model. Coefficients can be read directly and checked against the true drivers. |
| Gradient boosting (scikit-learn) | Challenger. Did not beat the main model. |
| Ceiling | The generator's true hazard without the hidden per-person effect. The best any model on these inputs can reach. |

## Evaluation

Time-based split: train on 2023-01 to 2025-09, test on 2025-10 to 2026-09 (48,907 person-months, 4,086 people at the first test month). Settings were fixed in advance, not tuned.

| Model | ROC AUC | Average precision | Brier |
|---|---|---|---|
| Logistic, monthly | 0.740 | 0.067 | 0.0177 |
| Gradient boosting, monthly | 0.733 | 0.064 | 0.0177 |
| Ceiling, monthly | 0.739 | 0.067 | 0.0177 |
| Logistic, 3-month risk | 0.722 | 0.144 | 0.0440 |

The main model sits at the ceiling. The remaining error is the per-person randomness built into the data, which no input explains. The base rate of a voluntary exit in a month is 1.8%, so average precision is low in absolute terms; it is 3.7 times the base rate.

The data was generated from a logistic formula, so a logistic model matching it is partly by design. On real data, gradient boosting should be expected to compete more closely.

## Do the coefficients match the truth?

| Effect (log-odds) | True | Estimated |
|---|---|---|
| Minijob vs full time | 1.00 | 1.03 |
| Part time vs full time | 0.25 | 0.32 |
| Tenure 0 to 5 months vs 24 to 60 | 0.90 | 1.00 |
| Pay ratio, per unit | -4.00 | -3.71 |
| Competitor pressure, per unit of log index | 0.80 | 0.71 |
| Manager changed in the last 6 months | 0.60 | 0.59 |
| Store vacancy rate, per unit | 2.50 | 2.42 |
| Fixed-term contract ending soon | 0.50 | 0.44 |
| January | 0.30 | 0.32 |
| Weekly hours (no true effect) | 0 | 0.00 |
| Apprentice vs full time | -1.00 | **-0.30** |

The apprentice effect is off because age is left out. Apprentices are young, youth raises the true risk, and the model attributes part of that to being an apprentice.

## Calibration

By decile, predicted and observed rates track closely (top decile 7.7% predicted, 6.7% observed). Overall the model predicts 2.06% against 1.84% observed in the test year: turnover drifts down slightly over the simulated period. In production the intercept would be re-estimated monthly.

## Fairness: calibration by age band

| Age band | Predicted | Observed | Ratio |
|---|---|---|---|
| under 25 | 2.15% | 2.49% | 0.87 |
| 25 to 34 | 2.15% | 1.83% | 1.17 |
| 35 to 44 | 1.73% | 1.43% | 1.21 |
| 45 to 54 | 1.75% | 1.74% | 1.01 |
| **55 and over** | **2.86%** | **1.46%** | **1.96** |

Leaving age out does not make the model neutral towards age. Many employees over 55 are retirees in minijobs. The model sees "minijob, high risk" but not the age effect that lowers it, so it rates them as nearly twice as likely to leave as they are.

Options, none free:
- Add age back as an input. Calibrates well, but uses a protected attribute in decisions about people.
- Report and act only on aggregates (store, region, contract type), never on individual scores. **This is what the project does**: individual scores stay in `hris`, the agent and dashboard see `mart` aggregates with groups under five dropped.
- Keep the band check in every retraining and treat a ratio outside 0.8 to 1.25 as a release blocker for any individual-level use.

## Explanations

Global importance as mean absolute SHAP value (exact for a linear model): tenure band 0.44, contract type 0.35, competitor pressure 0.19, pay ratio 0.15, store vacancy 0.08, manager change 0.08. Each scored person also gets their three largest risk-raising drivers, relative to an average employee; these stay in `hris.attrition_scores`.

## Intended use

Planning at store and region level: where to expect leavers in the next quarter, which levers (pay, staffing, manager continuity) matter most. Not for decisions about individual employees; in a real company that would also need works council agreement under §87 BetrVG.
