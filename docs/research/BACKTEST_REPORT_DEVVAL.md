# P6 backtest report: development + validation (holdout NOT opened)

Generated from `results/p6/devval.json` (code ee30a23c, engine replay-1, dataset hash 72d57c0048b62a06, config hash 7b74128335c99bb4).
Protocol: BACKTEST_PREREGISTRATION.md + BACKTEST_IMPLEMENTATION_CLARIFICATIONS.md (frozen before the run). Data: MetaQuotes-Demo XAUUSD bars, span 2025-10-14 to 2026-10-14 (server time); development to 2026-05-21, validation to 2026-08-02; the holdout (last 20%) bars are read from the store but dropped before any computation and never enter a result.

## Verdict

**INSUFFICIENT_EVIDENCE**: cand-1 (C4) produced 7 validation trades (minimum 20); holdout may open: **False**. The holdout stays sealed. No claim of an edge can be made, and none is made: the sample is a few dozen trades over about eight months.

## Per candidate and segment (base cost: spread + 0.1 USD/oz slippage per side, commission 0; R = net P/L / planned stop distance)

| Cand | Segment | n | mean R | win % | 95% CI of mean R (day bootstrap) | mean R @ slip 0.3 | @ +7 USD/lot | @ spread floor 0.2 | @ spread floor 0.4 | optimistic bound | ambiguous bars |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C3 | dev | 21 | 0.25 | 43 | [-0.36, 0.87] | 0.23 | 0.25 | 0.25 | 0.23 | 0.25 | 0 |
| C3 | val | 4 | 0.49 | 50 | [-1.01, 1.99] | 0.48 | 0.49 | 0.48 | 0.47 | 0.49 | 0 |
| C3 | wf1 | 5 | -0.42 | 20 | [-1.03, 0.78] | -0.44 | -0.43 | -0.43 | -0.44 | -0.42 | 0 |
| C3 | wf2 | 5 | 0.72 | 60 | [-0.49, 1.92] | 0.69 | 0.71 | 0.71 | 0.69 | 0.72 | 0 |
| C3 | wf3 | 11 | 0.35 | 45 | [-0.42, 1.17] | 0.33 | 0.35 | 0.34 | 0.33 | 0.35 | 0 |
| C3 | wf4 | 4 | 0.49 | 50 | [-1.01, 1.99] | 0.48 | 0.49 | 0.48 | 0.47 | 0.49 | 0 |
| C4 | dev | 21 | 0.61 | 38 | [-0.33, 1.61] | 0.58 | 0.60 | 0.60 | 0.58 | 0.61 | 0 |
| C4 | val | 7 | 0.73 | 57 | [-0.53, 1.71] | 0.70 | 0.73 | 0.72 | 0.70 | 0.73 | 0 |
| C4 | wf1 | 5 | 1.39 | 60 | [-0.29, 3.07] | 1.35 | 1.38 | 1.38 | 1.35 | 1.39 | 0 |
| C4 | wf2 | 11 | 0.34 | 36 | [-0.69, 1.67] | 0.32 | 0.34 | 0.33 | 0.32 | 0.34 | 0 |
| C4 | wf3 | 5 | 0.40 | 20 | [-1.03, 3.25] | 0.37 | 0.40 | 0.39 | 0.37 | 0.40 | 0 |
| C4 | wf4 | 8 | 0.51 | 50 | [-0.60, 1.66] | 0.48 | 0.51 | 0.50 | 0.48 | 0.51 | 0 |
| C5 | dev | 32 | 0.23 | 31 | [-0.37, 0.91] | 0.20 | 0.22 | 0.22 | 0.20 | 0.23 | 0 |
| C5 | val | 7 | 0.73 | 57 | [-0.53, 1.71] | 0.70 | 0.73 | 0.72 | 0.70 | 0.73 | 0 |
| C5 | wf1 | 6 | 1.00 | 50 | [-0.40, 2.46] | 0.96 | 0.99 | 0.99 | 0.96 | 1.00 | 0 |
| C5 | wf2 | 21 | -0.03 | 29 | [-0.61, 0.59] | -0.06 | -0.04 | -0.04 | -0.05 | -0.03 | 0 |
| C5 | wf3 | 5 | 0.40 | 20 | [-1.03, 3.25] | 0.37 | 0.40 | 0.39 | 0.37 | 0.40 | 0 |
| C5 | wf4 | 8 | 0.51 | 50 | [-0.60, 1.66] | 0.48 | 0.51 | 0.50 | 0.48 | 0.51 | 0 |
| C6 | dev | 21 | 0.61 | 38 | [-0.33, 1.61] | 0.58 | 0.60 | 0.60 | 0.58 | 0.61 | 0 |
| C6 | val | 7 | 0.73 | 57 | [-0.53, 1.71] | 0.70 | 0.73 | 0.72 | 0.70 | 0.73 | 0 |
| C6 | wf1 | 5 | 1.39 | 60 | [-0.29, 3.07] | 1.35 | 1.38 | 1.38 | 1.35 | 1.39 | 0 |
| C6 | wf2 | 11 | 0.34 | 36 | [-0.69, 1.67] | 0.32 | 0.34 | 0.33 | 0.32 | 0.34 | 0 |
| C6 | wf3 | 5 | 0.40 | 20 | [-1.03, 3.25] | 0.37 | 0.40 | 0.39 | 0.37 | 0.40 | 0 |
| C6 | wf4 | 8 | 0.51 | 50 | [-0.60, 1.66] | 0.48 | 0.51 | 0.50 | 0.48 | 0.51 | 0 |
| C7 | dev | 7 | 1.10 | 57 | [-0.45, 2.42] | 1.07 | 1.09 | 1.09 | 1.07 | 1.10 | 0 |
| C7 | val | 3 | -0.02 | 33 | [-1.05, 2.02] | -0.06 | -0.03 | -0.04 | -0.06 | -0.02 | 0 |
| C7 | wf1 | 2 | 0.95 | 50 | [-1.03, 2.94] | 0.91 | 0.95 | 0.94 | 0.91 | 0.95 | 0 |
| C7 | wf2 | 5 | 1.16 | 60 | [-0.45, 2.77] | 1.14 | 1.15 | 1.15 | 1.13 | 1.16 | 0 |
| C7 | wf3 | 0 | | | | | | | | | |
| C7 | wf4 | 3 | -0.02 | 33 | [-1.05, 2.02] | -0.06 | -0.03 | -0.04 | -0.06 | -0.02 | 0 |

C0 (always WAIT) trades nothing by definition. C6 reproduces C4 exactly (identical trade fingerprints: True) because setup-1 never uses liquidity-sweep evidence; it is a null control, not an independent ablation.

## C1 random entries with C4 geometry (500 seeds)

| Segment | seeds | C4 mean R | C1 p5 | p50 | p95 | C4 above C1 p95 | share of seeds >= C4 |
|---|---|---|---|---|---|---|---|
| dev | 500 | 0.61 | -0.59 | 0.00 | 0.67 | False | 0.07 |
| val | 500 | 0.73 | -1.02 | -0.14 | 0.99 | False | 0.09 |
| wf1 | 500 | 1.39 | -1.05 | -0.17 | 1.53 | False | 0.06 |
| wf2 | 500 | 0.34 | -0.72 | 0.06 | 1.04 | False | 0.33 |
| wf3 | 500 | 0.40 | -1.02 | -0.16 | 1.45 | False | 0.27 |
| wf4 | 500 | 0.51 | -0.82 | -0.06 | 0.94 | False | 0.14 |

## C2 buy-and-hold (USD per ounce, one fixed lot, includes one spread)

- dev: 420.86
- val: -476.05
- wf1: 379.48
- wf2: 565.99
- wf3: -524.88
- wf4: -494.53

## C4 decomposition

- Decisions not traded / skipped (whole development+validation span): {"NOT_TRADED:RISK:RR_TOO_LOW": 19, "NOT_TRADED:RISK:SL_TOO_CLOSE": 12, "NO_FILL:NO_BAR_AT_FILL": 1, "SKIPPED_POSITION_OPEN": 1}
- dev: by direction {"BUY": [7, 1.1], "SELL": [14, 0.36]}; by H1 context {"DOWN": [13, 0.46], "NONE": [1, -1.01], "UP": [7, 1.1]}; by server session {"00-08": [5, 2.0], "08-16": [5, 0.38], "16-24": [11, 0.07]}; month concentration 0.23
- val: by direction {"BUY": [3, -0.02], "SELL": [4, 1.3]}; by H1 context {"DOWN": [4, 1.3], "UP": [3, -0.02]}; by server session {"00-08": [4, 1.31], "08-16": [1, -1.01], "16-24": [2, 0.45]}; month concentration 0.99

## Reading this honestly

- Point estimates of mean R for C4 are positive in development and validation, but every 95% interval includes zero and the counts are tiny (see n). This is exactly the situation the pre-registration calls INSUFFICIENT_EVIDENCE.
- **Spread caveat (independent review):** the stored M5 `spread` field is not a stable real spread: monthly medians are 0.13-0.16 USD in Oct-Nov 2025, a constant 0.04 from Jan to May 2026, 52% zero bars in June 2026 and 0.10-0.14 later. Most dev/val fills therefore paid 0.04 or 0.00; the 'net of spread' figures are effectively 'net of the 0.1 slippage'. The spread-floor columns (0.2 / 0.4 USD) are the realistic sensitivity and must be read before any holdout is interpreted: a later period with larger spreads is a cost-regime change, not evidence about the strategy.
- **Power:** C4 produced 28-29 trades in about eight months. A 73-day holdout would yield roughly 7 trades, so the pre-registered 100-trade holdout threshold is unreachable with this data: the holdout could only ever return INSUFFICIENT_EVIDENCE. More history (M15 bars exist for a year only) or more candidates would be needed for a real test.
- C3 (trend onset only) is also positive in the same periods: the period contained a large up-trend followed by a drop (C2), so direction-agnostic comparisons are fragile.
- C5 is not a pure zone removal: a real zone that is touched without a pattern bar still goes to AT_RELEVANT_ZONE; the pseudo-zone path only applies when no zone exists. The pseudo-zone skips the 'zone above the impulse start' check.
- Selection effects: one trade per setup at its first eligible bar; 31 of 60 eligible decisions were blocked by risk-1 (RR_TOO_LOW or SL_TOO_CLOSE with the 6 USD stops level measured on MetaQuotes-Demo); trades unresolved at the segment end are dropped; the timeout is 288 M5 BARS (not 24 h: market breaks make a held trade span longer).
- Earlier structural experiments (swing-k grid, setup lifecycle) looked at the full year including what is now the holdout, but no outcome (P/L) was used: the contamination is structure-only.
- Many eligible setups were BLOCKED by the broker stops level or the net R:R floor: those decisions are counted, not hidden.
- Limits: spread is a bar value, not tick exact; one instrument, one broker feed, one regime period; demo data; bar-level fills (stop/target ambiguity resolved against the trade, SELL stops triggered on the ask); M5 holes not independently audited beyond the existing data QA.
