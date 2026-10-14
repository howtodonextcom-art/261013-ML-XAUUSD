# P6 implementation clarifications (written and committed BEFORE any backtest run; they fill gaps, they do not change BACKTEST_PREREGISTRATION.md)

Date: 2026-10-14. No backtest result has been seen when this file is committed. Any later change is an amendment with a reason and the original protocol's results are still reported.

## Timeline and execution
- Decision timeframe: M15 setups (setup-1), H1 direction, H4 conflict (configs/risk/policy.json). A decision is made at the CLOSE of an M15 bar from closed bars only; the hypothetical order is filled at the OPEN of the first M5 bar starting at or after that close (next-bar fill, never the same bar).
- Execution is simulated on M5 bars with the existing shadow-1 simulator (bid chart; BUY pays ask = open + spread + slippage, SELL sells bid; SELL stops/targets cost the spread on exit). Spread units: the stored `spread` field is in broker points; price = points x tick_size (0.01 for XAUUSD). The spread of the fill bar is used.
- Same M5 bar touching both levels: SL_FIRST_CONSERVATIVE (counted and reported; sensitivity with the optimistic TP-first reading is reported as a bound).
- Timeout: 288 M5 bars (24 h) then close at the bar close. Chase limit: 1.0 ATR(M15) beyond the planned entry => NO_FILL (not a trade, counted).
- Data ended before exit => the trade is dropped from the segment and counted.

## Trade selection
- One trade per `setup_id`, at its FIRST ENTRY_ELIGIBLE event. One open position at a time per candidate: eligible events during an open position are skipped and counted.
- The decision is built with the real `decide()` path (gates + risk-1 plan, target = impulse extreme). Hypothetical account for sizing only: equity = free margin = 100 000 (results are reported in R, never in money), measured spec: contract 100, value per unit 100 per lot, step 0.01, broker stops level 600 points. BLOCKED decisions are not traded and are counted by reason.
- R definition: net price P/L (after spread, slippage, commission) divided by the planned structural stop distance |entry - SL|.
- Cost levels change only the SIMULATION (slippage 0 / 0.1 / 0.3 USD per ounce per side, replacing the 0.5 x spread allowance of risk-1; commission 0 / 7 USD per lot round turn). The trade SET is identical across cost levels because it is decided by the product's own risk-1 gates.

## Candidates, where the pre-registration was thin
- C3: signal at each ONSET of an H4 direction (dir-1) change to UP/DOWN; decision at the next M15 close; SL = 1.5 x ATR(14, M15); TP = 2.0 x the stop distance; same risk-1/gate-1 plan checks and one position at a time.
- C1: per seed, for each C4 trade a uniformly random M5 bar of the same segment, a fair-coin direction, the stop and target distances of that C4 trade; same plan checks and simulator. 500 seeds (seed = 20261014 + k).
- C2: buy-and-hold of one fixed lot per segment: price change from the first to the last M5 bar plus one spread; reported in USD per ounce only (no R).
- C5: setup-1 with the ZONE requirement removed: after a pullback starts, the first bullish/bearish pattern bar confirms (its own range is the pseudo-zone); everything else equal.
- C6: the pre-registered "liquidity-sweep evidence removed" ablation is DEGENERATE: setup-1 / cand-1 never uses liquidity-sweep evidence, so C6 == C4 exactly. This is reported, not hidden; C6 is a null control that must reproduce C4's trade list.
- C7: C4 restricted to BUY.

## Segments and isolation
- Span: first to last stored M5 bar. Development = first 60% of the span (by time), validation = next 20%, holdout = last 20%. 24 h embargo after each boundary: decisions inside the embargo belong to no segment. A trade decided before a boundary whose exit lies after it is dropped from the earlier segment (no holdout prices in earlier results).
- Dev/validation runs load bars strictly BEFORE the holdout start; the holdout bars never enter memory. The holdout run refuses to start without a seal file recording code SHA, config hash and dataset hashes, and writes an irreversible "opened" marker; a second run is refused.
- Walk-forward: the development+validation span is cut into 4 equal consecutive time blocks; each is evaluated independently with frozen parameters (no parameter is fitted anywhere, so expanding training windows would change nothing and are not simulated).
- Validation gate (needed because the pre-registration says "only if it passes validation first"): C4 reaches the holdout only if on the validation segment it has at least 20 trades and mean R > 0 at base cost. With fewer than 20 validation trades the verdict is INSUFFICIENT_EVIDENCE and the holdout stays sealed.
- Bootstrap: resample calendar days (block = day) of trade R, 2000 resamples, seed 20261014.

## Required before the first result is looked at
Synthetic-data tests of the engine, hand-calculated trade examples for the simulator, prefix-invariance (lookahead) test on real data, determinism test (two runs, byte-identical trade lists).
