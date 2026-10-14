# Research status (what is and is not known about the strategy)

**There is no demonstrated trading edge.** The software works; whether the rules make money is a separate question, and the evidence so far says "not shown".

| Study | Question | Status | Evidence |
|---|---|---|---|
| P6 V1 backtest (`cand-1` and controls C0 to C7) | positive out-of-sample expectancy after costs? | **INSUFFICIENT_EVIDENCE** | 7 validation trades (minimum 20); every 95% interval includes zero; holdout **sealed and never opened**; the pre-registered 100-trade holdout rule is unreachable (about 7 expected trades). docs/research/BACKTEST_REPORT_DEVVAL.md, BACKTEST_AMENDMENTS.md |
| P7 ML shadow (logistic, 14 point-in-time features) | predicts the 4-bar direction? | **NO_EVIDENCE_OF_PREDICTIVE_SKILL** | validation AUC 0.499 [0.474, 0.525]; it feeds nothing and is not a signal. ML_SHADOW_REPORT_DEVVAL.md, ML_SHADOW_AMENDMENTS.md |
| V2 M1 entry intelligence (shadow) | do M1 triggers at an M15 zone after an M5 confirmation have positive net expectancy? | **FORWARD_SHADOW_COLLECTING, no performance claim** | protocol committed before any code (afd688e, M1_ENTRY_V2_PREREGISTRATION.md). All stored M1 history lies inside the sealed holdout period, so there is NO historical evidence and none will be computed; events are logged forward in time only (`data\shadow\v2_events.jsonl`); evaluation is allowed after at least 100 triggers AND 30 days. A counts-only history funnel (no outcomes) exists: results/v2/funnel_history.json |

## Rules that protect the conclusions
- BACKTEST_PREREGISTRATION.md, BACKTEST_IMPLEMENTATION_CLARIFICATIONS.md and ML_SHADOW_PREREGISTRATION.md are frozen. Differences found later are recorded in the *_AMENDMENTS.md files, never edited into the originals.
- The sealed holdout is not opened to "see if it helped"; no threshold or candidate is tuned to raise the trade count on data already seen; a Candidate V3 would need its own registration, its own clock and new data.
- Fixture results (BUY/SELL displayed from synthetic scenarios) prove the display, not the market. **A live BUY/SELL has not been observed.**

## Known data caveats
The stored M5 spread is mostly 0.04 or 0.00 (spread-floor sensitivity 0.2 / 0.4 USD must be read); MT5 keeps about 100 000 M1 bars (about 70 days); M1 history has real holes (reported, not filled); one instrument, one broker feed, demo data; the broker stops level (6.00 USD) blocks many M1-scale stops.

## What would change the status
More weeks of forward shadow data for V2 (then the pre-registered evaluation, whatever it says); more history for a new, separately registered V1 study; an honest holdout opened once under its own rules. None of these is available today.

## V2 evaluation protocol clarifications
Implementation clarifications and corrections to the V2 evaluator and log (SELL price mirroring, zone selection, week concentration, v1_target timing, gap-safe entry and timeout, UTC/DST clock, log integrity) are recorded in `docs/research/M1_ENTRY_V2_AMENDMENTS.md` (A1-A14). The registration is unedited; no evaluation has run (the gate is closed until 100 triggers AND 30 days).

## State of the V2 forward evidence (2026-10-14, Level 5.6)
- Collecting live since the registration instant: 13 triggers so far; the gate (>= 100 triggers AND >= 30 calendar days, a pure UTC difference from 1791960048) is closed, `benchmarks/v2_shadow_eval.py` refuses and reads no price. No performance figure exists. `results/v2/forward_eval.json` does not exist.
- Evaluation prerequisites that a future run must meet (all in `M1_ENTRY_V2_AMENDMENTS.md`): UTC-keyed bars with evidence-only offsets (A12-A14), recurring-signature closures, outcome-independent window rules (A8, A11), the 40 legacy events reported with and without (A5/A11). Events before `log_schema` 2 had mirrored SELL prices (A1, repaired on read).
- Unchanged: P6 INSUFFICIENT_EVIDENCE (holdout sealed), P7 NO_EVIDENCE_OF_PREDICTIVE_SKILL. Statistical uncertainty: with 7 validation trades (V1) and 0 evaluated V2 trades no confidence interval means anything.
