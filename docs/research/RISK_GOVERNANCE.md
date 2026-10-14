# RISK GOVERNANCE (P5): paper decisions, planned risk, shadow outcome

Scope: `xau_intel/decision` (`risk.py`, `decide.py`, `shadow.py`) and `xau_gateway/symbol_spec.py`. Everything is research/paper. **No code path can send, modify or cancel an order**: `execution_authorized` is a constant False, there is no order function in any shipped source (static scan test), and the only MT5 helpers used for risk are the pure calculators `order_calc_profit` / `order_calc_margin`.
Configuration: `configs/risk/policy.json` (no secrets; `null` = not configured, not evaluated). All values are initial design parameters, unvalidated.

## Three separate permissions
1. **Strategy Eligible**: an active setup in state ENTRY_ELIGIBLE (SETUP_LIFECYCLE.md). Only the setup machine can make it true; there is no input for RSI, MACD or EMA crossovers.
2. **Risk Eligible**: the risk plan status is OK (below).
3. **Execution Authorized**: always False in this release.
A decision is BUY/SELL only when 1 and 2 hold and every gate passes. Eligible but gate/risk failing => BLOCKED with `strategy_eligible: true`. Not eligible => WAIT with the STRATEGY (or market) reason as the headline, gates only listed (a risk gate never hides an unformed setup). Stale data => WAIT/DATA_STALE (never a new decision).

## Risk plan (bid-chart coordinates)
loss distance = |entry - invalidation| + spread + slippage (+ commission/value); reward = |target - entry| - spread - slippage (- commission). Stop = the setup's invalidation level (structural: below the confirmation bar low and the zone, minus 0.25 ATR). Target = the impulse extreme in the trade direction (structure target); TP2 = 2R reference, never an exit rule. Net R:R must be >= `min_net_rr`.
Lot = risk budget (equity x risk_fraction) / loss per lot, **rounded down** to the volume step; minimum lot above the budget => BLOCKED (RISK_MIN_LOT_EXCEEDS_BUDGET). Margin = MT5's own margin per lot scaled by price; if free margin is lower => BLOCKED. Broker minimum stop distance respected.
Missing spec, equity, free margin, spread or ATR => **RISK_NOT_EVALUABLE** (never eligible). Equity and free margin are in memory only: never stored or logged. The API publishes only `RiskPlan.public_plan()`: no budget, no loss or margin amounts, no unrounded lot, no value per unit; reason texts are constant strings without any number (ratios were invertible, review round 6); a BLOCKED (non-eligible) plan carries levels and R:R but no lot. **Limit (honest):** the rounded `lot` together with `risk_fraction` and the public contract size still bounds the account size to within the lot-step rounding, so equity is approximately inferable from a published lot. Review round 6b quantified it: for an ELIGIBLE decision the published lot, risk_fraction, stop distance and spread bound equity to about step/lot (about 2% at lot 0.5) and intersecting observations at different loss distances narrow it to about 0.2% within a few dozen frames; the BLOCKED reasons RISK_MIN_LOT_EXCEEDS_BUDGET and INSUFFICIENT_MARGIN flip at exact thresholds, which acts as an oracle for equity and free margin while the entry moves. These are inherent in showing a size and a feasibility verdict; the protection is the loopback binding, the Host/Origin guard (a web page cannot read the stream) and, still missing, authentication against other local processes. The API is loopback-only and unauthenticated; remote access must not be enabled before authentication exists.

## Measured fact that justified the design (MetaQuotes-Demo XAUUSD, 2026-10-14, `scripts/windows/probe_symbol_spec.py`)
`order_calc_profit(1 lot, +1.00)` = 100 USD (agrees with contract size 100), but the broker's `trade_tick_value` = 0.1 with tick size 0.01 implies only 10 USD. Using the tick value would size lots 10x too large. The engine uses the larger value (smaller lot), records `VALUE_PER_UNIT_SOURCES_DISAGREE`, and never assumes "1 lot = 100 oz" without the cross-check. `order_calc_margin(1 lot)` = 4 159.68 = price x 100 / leverage 100.

## Shadow outcome (no hindsight)
Decision known at a bar close; fill at the NEXT bar open (BUY pays spread + slippage, SELL sells the bid). Fill farther than the chase limit, beyond the stop, or beyond the target => NO_FILL (counts as a missed opportunity, never a win). Outcomes: TP_FIRST, SL_FIRST, SL_FIRST_CONSERVATIVE (distinct label), TIMEOUT, INCONCLUSIVE (both levels in one bar without a tick path), NO_FILL, NO_DATA. Tick paths can order TP/SL inside a bar. `r_multiple` = net price P/L / planned loss distance with costs.

## Evidence
tests/unit/test_risk.py (12), test_decide.py (18), test_shadow.py (14), test_symbol_spec.py (3): exact hand-computed lots and net R:R, invalid stop/target, margin, min lot, missing data, broker stops level, SELL mirror in distances/lot/R:R, gate layering, stale/market closed/spread/daily loss (configured only), random-market property (BUY/SELL only after ENTRY_ELIGIBLE with clean gates), fill guards, no dependence on bars after the exit. A property test caught a real simulator bug (a fill beyond the stop produced a positive "SL" result): fixed, regression test added.

## Limits (honest)
- No account ledger exists: `daily_loss_used_fraction` is not tracked, so the daily-loss gate is not evaluable until a paper ledger exists (it is off by default, and FTMO or any programme limit must come from a verified configuration, never from code).
- Commission is unknown for this demo (0 assumed and reported). Slippage allowance is a parameter (0.5 x spread per side), not a measurement.
- Target = impulse high is a structure rule, not a forecast; an unrealistic target (too close) simply fails the net R:R gate.
- Shadow results use bars unless ticks are supplied; they are not yet aggregated into a backtest (P6).
