# Backtest pre-registration (P6) — written and committed BEFORE any backtest code exists or runs

Status: PRE-REGISTERED. Nothing below has been run. Any change after the first run must be recorded as an amendment with the reason; results of the original protocol are always reported.

## Question
Does the research candidate `cand-1` (setup-1 + risk-1 + gate-1) show a positive net expectancy after costs on out-of-sample XAUUSD data, better than simple baselines? The expected honest answer may be INSUFFICIENT_EVIDENCE.

## Data
- Source: the verified local store (MetaQuotes-Demo). Bars M5 (365 days), M15 (365), H1 (365), H4 (730); M1 and 14 days of ticks.
- Bars excluded when flagged (M1_HISTORY_HOLE buckets, quarantined bars, PARTIAL bars). No filling of holes.
- Decisions use point-in-time snapshots of CLOSED bars only (existing snapshot rule). Entry is simulated at the NEXT bar open after the decision (no same-bar fill), using the bid/ask model below.

## Splits (chronological, fixed now)
- Development: first 60% of the available M5 span. Validation: next 20%. Holdout: last 20%, touched exactly ONCE, after all candidate definitions and parameters are frozen.
- Walk-forward on development+validation: 4 expanding folds, test blocks never overlap, no parameter fitted on a later block.
- Embargo: 24 h between split boundaries; a trade open at a boundary is dropped from the later segment.

## Candidates (definitions frozen; parameters are the defaults already in the repository, no tuning)
- C0: always WAIT (zero trades; sanity baseline).
- C1: random entry at the same frequency as C4, direction by fair coin, same stop/target geometry (500 seeds; report distribution).
- C2: buy-and-hold one fixed lot over each test segment (market drift reference).
- C3: H4 trend direction only (dir-1), enter on next M15 open, ATR stop, same net R:R floor.
- C4: `cand-1` as implemented (setup-1 ENTRY_ELIGIBLE + gate-1 + risk-1 OK).
- C5: C4 with the zone/pullback requirement removed (ablation).
- C6: C4 with the liquidity-sweep evidence removed (ablation).
- C7: C4 with the sell side disabled (asymmetry check).
No indicator-only candidate may be added after seeing results.

## Cost model (sensitivity mandatory)
Base: recorded spread at the bar (M5 bars carry spread); slippage 0 / 0.1 / 0.3 USD per ounce; commission 0 (demo) with a +7 USD per lot round-turn sensitivity. Results reported at all levels; the decision uses the 0.1 USD slippage + spread case.

## Metrics
Trades, win rate, mean R, net expectancy per trade with bootstrap 95% CI (block bootstrap by day, 2000 resamples), profit factor, max drawdown (R), longest losing streak, exposure, trades per week, result by direction, by session, by regime, by month. Fills use the shadow simulator (shadow-1) semantics, including conservative stop-first ordering when stop and target are inside one bar.

## Decision rule (frozen)
A candidate is judged on the HOLDOUT only if it passes validation first. C4 is declared "shows evidence" only if ALL hold: at least 100 holdout trades; net expectancy > 0 at the base cost AND at +0.3 slippage; bootstrap 95% lower bound of mean R > 0; beats C1 at the 95th percentile of the random distribution and beats C3; positive in at least 3 of 4 walk-forward folds; no single month contributes more than 50% of total R. If trades < 100: INSUFFICIENT_EVIDENCE (not a pass, not a fail). Anything else: NO_EVIDENCE_OF_EDGE. Multiple-comparison note: 8 candidates are tested; only C4 is the primary hypothesis, others are controls and not eligible for a win claim.

## Guards against self-deception
- Parameters frozen before the first run; no re-running with altered thresholds on the holdout.
- Lookahead test: truncating future bars must not change any past decision (automated test required before the run).
- Determinism test: two runs give byte-identical trade lists.
- Report negative and null results in full; no cherry-picked windows.

## Limits known in advance
Spread is a bar value, not tick-exact; ticks cover only 14 days so tick-level fills are not validated for the full year; one instrument, one broker feed, one regime period (about one to two years); demo data is not live execution.
