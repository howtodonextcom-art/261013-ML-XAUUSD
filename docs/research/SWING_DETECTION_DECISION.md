# SWING DETECTION: PRE-REGISTERED DECISION (rule text written before the result was computed; self-attested)

Question: which causal swing-point detector feeds the Market Structure engine (HH/HL/LH/LL, BOS, CHoCH)?

## Candidates
- **A. Fractal(n)**: a bar is a swing high if its high is strictly greater than the highs of the n bars on each side (mirror for lows). Confirmed when the n-th bar after it closes. n = 3 (pre-set, not tuned).
- **B. ATR zig-zag(k)**: a swing is confirmed when price retraces at least k x ATR14 from the running extreme. k = 2.0 (pre-set, not tuned).
- **C. Hybrid**: not built (it only makes sense if A and B both fail a gate).

## Evidence set
Stored MetaQuotes-Demo XAUUSD bars, M15 and H1, last 120 and 365 days respectively (`data/store`, source `mt5_hist_bars`). No outcomes (profit, win rate) are used: the choice is about the detector's properties, not about trading results.

## Hard gates (must pass or the candidate is rejected)
G1 **No look-ahead**: swings known at index c computed on the series truncated at c equal those computed on the full series restricted to `known_idx <= c` (property test on random walks and on real bars).
G2 **No repaint**: a swing, once emitted, never changes or disappears when more bars arrive (same test, all cut points).
G3 Every swing carries `formed_at`, `known_at` (`known_at > formed_at`), `evaluated_at`, `source_timeframe`, `feature_version`.

## Soft criteria (compared only among candidates that pass the gates)
S1 Swing density between 4 and 10 swings per 100 bars on both M15 and H1.
S2 Median confirmation delay (bars between the extreme and `known_at`): lower is better, but a detector is not preferred for speed alone if S1 fails.
S3 Complexity / parameters: fewer is better.

## Decision rule
Pick the candidate that passes G1-G3 and S1. If both pass, pick the one with the smaller median delay; on a tie within 1 bar, pick A (simplest). If neither passes S1, keep the gate-passing candidate closer to the density band and record the failure. The parameters n=3 and k=2.0 are fixed here and are not re-tuned after seeing the result.

## Result
See the section below, appended after the run (the rule above is not edited).

### Run on 2026-10-14 (`benchmarks/swing_detector_eval.py`, MetaQuotes-Demo XAUUSD, local store)
| TF (bars) | Detector | swings | per 100 bars | median delay (bars) | G1 | G2 | G3 | cut points |
|---|---|---|---|---|---|---|---|---|
| M15 (7 540, 120 d) | fractal n=3 | 1 427 | 18.93 | 3 | pass | pass | pass | 59 |
| M15 | ATR zig-zag k=2.0 | 855 | 11.34 | 2 | pass | pass | pass | 59 |
| H1 (5 773, 365 d) | fractal n=3 | 1 107 | 19.18 | 3 | pass | pass | pass | 58 |
| H1 | ATR zig-zag k=2.0 | 661 | 11.45 | 3 | pass | pass | pass | 58 |

Applying the rule exactly as written: both pass the hard gates; **neither passes S1** (density band 4-10 per 100 bars): fractal is at about 19, zig-zag at about 11.4.
Clause "if neither passes S1, keep the gate-passing candidate closer to the density band and record the failure" => **selected: ATR zig-zag (k = 2.0)**. Median delay is not worse (2 vs 3 bars on M15, equal on H1).
S1 failure is recorded, not hidden: even the selected detector yields slightly more swings than the band allows. Parameters were NOT re-tuned after seeing this. A larger k would be a new pre-registered experiment, not a patch to this one.
Limits: one instrument, one broker feed, one period; the gates were checked at about 60 cut points per series (a sample, not every index; the unit property tests cover every 7th index on random walks). No trading outcome was used.

### Honest limits of the pre-registration (added after the independent review)
- The rule text was written before the evaluation script was run, but **there is no external timestamp**: this file was not committed before the run, and it also contains the result. The claim "written before" is the implementer's own statement, verifiable only by the 23 s gap between the script's and the document's file modification times, which proves nothing. Future pre-registrations are committed (and pushed) **before** the experiment is run.
- The density band (4-10 per 100 bars) was failed by both candidates. Selecting the zig-zag therefore came from the fallback clause, not from meeting the criterion. Treat the detector as "acceptable on causality, noisy on density", not as validated structure.
- The gates were sampled at about 60 cut points on real bars (plus every 7th index on random walks in the unit tests), not at every index.
