# PRE-REGISTRATION: ATR zig-zag threshold k (committed and pushed BEFORE the experiment is run)

Context: docs/research/SWING_DETECTION_DECISION.md recorded that ATR zig-zag with k = 2.0 passed the causality gates but produced 11.3-11.5 swings per 100 bars, above the 4-10 band. This is a NEW experiment, not a patch to that one.

## Question
Which k in the fixed grid {2.5, 3.0, 4.0} brings swing density into the band on BOTH M15 and H1 while keeping the causality gates?

## Fixed before running
- Grid: k in {2.5, 3.0, 4.0}. No other value is tried. ATR is the existing ATR14 (SMA of TR). The zig-zag initialisation is the corrected one (both running extremes tracked until one side retraces k*ATR); the implementation change is committed together with its tests before this experiment is run.
- Data: stored MetaQuotes-Demo XAUUSD native bars, M15 last 120 days, H1 last 365 days (same windows as before).
- Gates (hard, per k and timeframe): G1 no look-ahead and G2 no repaint, checked at the same sampled cut points as the earlier run (about 60 per series); G3 timestamp fields.
- Soft criterion S1: density between 4 and 10 swings per 100 bars on both timeframes.
- Secondary (report only): median confirmation delay in bars.

## Decision rule
Among k values that pass the gates and S1 on both timeframes, choose the SMALLEST k (earliest confirmation). If none passes S1, record the failure, keep k = 2.0 and do not run further k values in this experiment; any further search needs a new pre-registration.
No trading outcome (profit, win rate) is used. Selection must not look at anything else than the table produced by `benchmarks/swing_detector_eval.py --k-grid`.

## Result
Appended after the run in a separate section; this text is not edited afterwards.
