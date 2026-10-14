# P7 ML shadow: pre-registration (written and committed BEFORE any ML code or run)

Status: PRE-REGISTERED, nothing has been run. Any change after the first run is an amendment with its reason; the original protocol's results are always reported.

## Role
A shadow model. Its output is stored and displayed separately from the rule engine; it never changes a decision, never feeds a gate, never authorizes execution (`execution_authorized` stays False). The question is only: does a simple, calibrated, point-in-time model predict the short-term direction of XAUUSD better than trivial baselines on data it has not seen?

## Data and isolation
- Bars: the same stored M15/H1/H4 bars as P6 (bars closed only). The SAME frozen boundaries as P6 (`results/p6/boundaries.json`): development = first 60%, validation = next 20%, **holdout = last 20% shared with P6 and sealed**. P7 never reads a bar at or after `val_end` in any computation, and never opens the holdout unless the P6 holdout is opened under its own rules; if it is, both are evaluated once, together, and the result is reported as a two-hypothesis test.
- Quarantined bars excluded; no repair; spread is NOT a feature (the stored M5 spread is unreliable, see BACKTEST_AMENDMENTS A6).

## Task
- Sample: every M15 bar close `i` (decision time = close of bar `i`).
- Label: `y_i = 1` if close[i+4] > close[i], 0 if lower, dropped if equal or if any of the next 4 bars is missing (a data gap). The label uses the future by definition and is only ever used as a target after the split.
- Embargo: samples whose horizon (4 bars) crosses a split boundary are dropped from the EARLIER side; 24 h gap after each boundary.

## Features (point in time, all from closed bars up to `i`; each computed with the repository's tested functions)
RSI(14); (close - EMA20)/ATR, (EMA20 - EMA50)/ATR; MACD histogram/ATR; ATR(14)/ATR(50) ratio; the last 1, 4, 16 bar returns divided by ATR; distance to the last confirmed swing high and low in ATR (zig-zag k=2.5, `known_at` respected); H1 direction and H4 direction as -1/0/+1 (dir-1, aligned to closed higher-timeframe bars); hour of the server day as sin/cos; day of week one-hot is NOT used (too few weeks). Missing values (warm-up) drop the sample. Standardisation uses the TRAINING mean/std only.

## Models and baselines (frozen, no search)
- M1: L2-regularised logistic regression, lambda = 1.0 on standardised features, fitted with a fixed deterministic Newton/IRLS routine (numpy; no random state).
- B0: constant prediction = training base rate.
- B1: momentum: probability from the sign of the last 4-bar return (logistic on that single feature, same fit).
- B2: H1-direction rule: UP -> p = training up-rate given UP, DOWN -> ..., NONE -> base rate.
No hyper-parameter is tuned; lambda is fixed now.

## Evaluation
- Fit on development only (no refit); score on validation. Walk-forward inside development for stability: 5 consecutive blocks, the model refitted on all earlier samples of development (expanding window), scored on the next block.
- Metrics: AUC (rank), Brier score, Brier skill vs B0, calibration slope and intercept (logistic recalibration of the logit), reliability table (10 bins, quantile), accuracy at p>0.5, number of samples. 95% intervals by block bootstrap of calendar days, 2000 resamples, seed 20261014.

## Decision rule (frozen)
M1 "shows predictive evidence" only if on VALIDATION all hold: AUC lower 95% bound > 0.5; Brier skill vs B0 > 0; calibration slope within [0.7, 1.3]; AUC(M1) > AUC(B1) and > AUC(B2); AUC > 0.5 in at least 4 of 5 development walk-forward blocks. Otherwise NO_EVIDENCE_OF_PREDICTIVE_SKILL. A positive validation is NOT a trading claim: it only licenses a shadow display and a later holdout test. Samples are autocorrelated (4-bar horizon on every bar), hence the day-block bootstrap; the effective sample size is far below the sample count and is reported.

## Guards
- Lookahead: features at bar i are identical when all later bars are removed or corrupted (automated test, mutation-checked); the label never enters a feature.
- Determinism: two runs give identical predictions (hash reported). Seeds are fixed; there is no randomness in the fit.
- Reporting: all metrics and negative results are reported; no cherry-picked block or threshold.

## Limits known in advance
One instrument, one broker feed, about 8 months of development+validation M15 bars (about 14 000 samples before the horizon/embargo drops, strongly autocorrelated), a regime in which gold moved strongly; a null result is the expected outcome and is a valid result.
