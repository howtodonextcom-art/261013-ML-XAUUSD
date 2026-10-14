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

### Result (run on 2026-10-14 after commit 49527a5; `benchmarks/swing_detector_eval.py --k-grid 2.5 3.0 4.0`)
| TF (bars) | k | swings | per 100 bars | S1 (4-10) | median delay (bars) | G1 | G2 | G3 | cut points |
|---|---|---|---|---|---|---|---|---|---|
| M15 (7 540) | 2.5 | 605 | 8.02 | pass | 4 | pass | pass | pass | 59 |
| M15 | 3.0 | 437 | 5.80 | pass | 5 | pass | pass | pass | 59 |
| M15 | 4.0 | 275 | 3.65 | fail | 11 | pass | pass | pass | 59 |
| H1 (5 773) | 2.5 | 431 | 7.47 | pass | 5 | pass | pass | pass | 58 |
| H1 | 3.0 | 307 | 5.32 | pass | 7 | pass | pass | pass | 58 |
| H1 | 4.0 | 183 | 3.17 | fail | 13 | pass | pass | pass | 58 |

Rule applied as written: k = 2.5 and 3.0 pass the gates and S1 on both timeframes; the smallest is **k = 2.5**. Selected: **ATR zig-zag k = 2.5**.
Cost recorded: confirmation is later than at k = 2.0 (median 4-5 bars versus 2-3), a direct trade-off between noise and speed. Swing counts exclude the window-start artifact. Sampled gates only (about 60 cut points), one instrument/feed/period, no trading outcome used. The earlier k = 2.0 choice is superseded by this result.

### Addendum after independent review round 3 (limits of this pre-registration; the text above is unchanged)
- The pre-registration (commit d01eca2, pushed to GitHub, so externally timestamped) came BEFORE the implementation commit (49527a5, about two minutes later) and the result. The text said the implementation change would be committed "together with" it; it was committed right after, not together.
- Degrees of freedom NOT locked by the pre-registration: the intra-bar High/Low ordering policy and the window-start artifact flag were added after k = 2.0 had already failed the density band; the k grid {2.5, 3.0, 4.0} was chosen after seeing that k = 2.0 was outside the band; the 4-10 band itself comes from the earlier experiment.
- Only M15 and H1 were evaluated. k = 2.5 is also used for M1, M5 and H4 in `analyse_tf` without any experiment on those timeframes.
- The sampled gates (about 60 cut points) are a sample, not every index.
