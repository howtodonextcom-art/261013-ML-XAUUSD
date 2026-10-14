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
