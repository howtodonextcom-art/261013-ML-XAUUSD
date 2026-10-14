# P7 ML shadow report: development + validation (holdout NOT loaded)

Generated from `results/p7/ml_devval.json` (code 00e6d47f, ml-1, dataset hash 72d57c0048b62a06, result fingerprint c9aa0a8d77cb63b1).
Protocol: ML_SHADOW_PREREGISTRATION.md (frozen before the run). Task: sign of the 4-bar (1 h) forward close change at every M15 close. Development to 2026-05-21, validation to 2026-08-02; the holdout shared with P6 was never loaded.

## Verdict

**NO_EVIDENCE_OF_PREDICTIVE_SKILL**

Samples: 12527 train, 4245 validation (usable rows overall 16860); validation up-rate 0.469. Effective independent days in validation: 51 (the samples overlap in time).

## Validation

| Model | AUC | AUC 95% (day bootstrap) | Brier skill vs base rate | calibration slope | accuracy |
|---|---|---|---|---|---|
| M1 | 0.499 | [0.474, 0.525] | -0.0003 | 0.050 | 0.479 |
| B0 | 0.500 | n/a | 0.0000 | n/a | 0.469 |
| B1 | 0.497 | [0.476, 0.519] | -0.0004 | -1.023 | 0.469 |
| B2 | 0.510 | [0.486, 0.533] | 0.0021 | 0.401 | 0.469 |

M1 = L2 logistic regression on 14 point-in-time features; B0 = base rate; B1 = 4-bar momentum; B2 = H1-direction lookup.

## Walk-forward inside development (expanding window, 5 scored blocks)

| Block | train n | test n | AUC M1 | AUC B1 | AUC B2 | Brier skill M1 |
|---|---|---|---|---|---|---|
| 1 | 1560 | 2190 | 0.502 | 0.510 | 0.522 | -0.0366 |
| 2 | 3754 | 2170 | 0.494 | 0.529 | 0.523 | -0.0146 |
| 3 | 5928 | 2181 | 0.511 | 0.519 | 0.494 | -0.0059 |
| 4 | 8109 | 2194 | 0.501 | 0.505 | 0.485 | -0.0055 |
| 5 | 10307 | 2216 | 0.498 | 0.499 | 0.531 | -0.0027 |

## Pre-registered rule

- auc_ci_lower_gt_0.5: False
- beats_B1_and_B2: False
- brier_skill_gt_0: False
- calibration_slope_in_0.7_1.3: False
- wf_blocks_auc_gt_0.5: 3
- wf_blocks_scored: 5

## Reading this honestly

- A validation AUC at or below 0.5 with an interval around 0.5 means the model has no demonstrated skill on this data; this was the expected outcome and is a valid result.
- Overlapping 4-bar labels on every bar make the samples strongly autocorrelated: the effective sample size is the number of independent days, not the number of rows.
- Nothing here is a trading claim and the model feeds nothing: it would only ever be displayed as a shadow signal.
- Limits: one instrument and broker feed, about eight months of development+validation, a strongly trending year; no hyper-parameter search was done (lambda fixed); spread is not a feature (the stored M5 spread is unreliable).
