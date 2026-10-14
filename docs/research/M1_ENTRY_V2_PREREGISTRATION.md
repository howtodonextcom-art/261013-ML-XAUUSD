# M1 Entry Intelligence, candidate V2 (SHADOW): pre-registration

Written and committed BEFORE any V2 code exists. Nothing here has been run. V2 is a separate candidate; V1 (`cand-1`: H1 direction, H4 conflict, M15 `setup-1`, `risk-1`, `gate-1`) and the frozen P6/P7 studies are untouched. V2 never changes a V1 decision, never feeds a gate, never authorises execution.

## Question
Does an M1 entry-timing layer (rejection / engulfing / momentum shift / local structure break at an M15 zone, after an M5 confirmation) produce entries with positive net expectancy after costs, better than trivial baselines, on data it has not been developed on?

## Dataset isolation (decided from the facts, before looking at any outcome)
- MT5 keeps about 100 000 M1 bars: the stored M1 history starts 2026-08-04 21:08, i.e. AFTER the V1/P6 `val_end` (2026-08-02): **all historical M1 data lies inside the sealed P6/P7 holdout period.** It is therefore NOT usable as unseen evidence for V2, and there is no earlier M1 development data.
- Consequence (registered): V2 gets **no historical performance claim at all**. Allowed on historical M1: synthetic-data correctness tests, no-lookahead tests, and a SIGNAL-FREQUENCY funnel (counts only, no price outcome, no P/L, no R). Any price outcome computed from a historical bar inside the sealed period is forbidden.
- V2 evidence comes only from **forward shadow data**: every V2 event produced live after the commit that registers this document is appended (one JSON line each, with the decision-time evidence) to `data/shadow/v2_events.jsonl` (git-ignored, append-only). Outcomes are computed later from bars that did not exist at registration.
- Evaluation is not allowed before BOTH: at least 100 TRIGGERED events AND at least 30 calendar days after the registration commit. Before that the status is INSUFFICIENT_EVIDENCE (a legitimate result).

## Layers (all causal; every event carries `known_at` = the close time of the bar that made it knowable)
- Context (H4/H1): V1's H1 direction series (`dir-1`) and the H4 conflict flag, aligned to CLOSED higher-timeframe bars. No context, or a conflict => no V2 stage beyond NO_CONTEXT.
- M15 zone: the nearest zone-1 zone (confirmed swings only, `known_at` respected) on the correct side of price: BUY needs a zone with `zone.high <= price + 0.25 ATR15` and `zone.high >= price - 2.0 ATR15`; SELL is the exact mirror.
- M5 confirmation: a closed M5 bar with an `pa-1` pattern in the context direction (pin / engulfing / strong close), whose range touches the zone (BUY: low <= zone.high and close > zone.low). It must be among the last 6 closed M5 bars. Known at that M5 bar's close.
- M1 trigger (closed M1 bars only, after the M5 confirmation was known, price inside the zone band `[zone.low - 0.25 ATR5, zone.high + 0.5 ATR5]`), any ONE of:
  1. `M1_REJECTION`: `pa-1` pin bar on M1 (ATR14 of M1).
  2. `M1_ENGULFING`: `pa-1` engulfing on M1.
  3. `M1_MOMENTUM_SHIFT`: close above the highest high of the previous 3 M1 bars, range >= 0.8 ATR(M1), after at least 2 lower closes in the previous 4 bars (SELL mirrored).
  4. `M1_STRUCTURE_BREAK`: close above the last CONFIRMED M1 zig-zag swing high (k = 2.5, `known_at` respected) (SELL mirrored).
- Intrabar observation (display only, never an event): while the current M1 bar is still forming, a wick-rejection geometry on the partial bar (`pa-1` pin proportions on the bar so far, range >= 0.5 ATR) is shown as `FORMING_REJECTION_CANDIDATE: unconfirmed, may disappear`. It is not logged as a V2 event, not part of any statistic, and is discarded at the bar close (it becomes a closed-bar event only if the CLOSED bar still satisfies the definition).

## Stages (per direction, recomputed from closed bars at every call: a pure function of bars known at that time, no hidden state)
NO_CONTEXT, NO_ZONE, WATCHING_ZONE (zone found, no M5 confirmation), M5_CONFIRMED_AWAITING_M1 (the M1 trigger is missing: e.g. a wick-rejection candle without the M5 confirmation or without a closed trigger bar stays WATCHING / AWAITING and is never shown as BUY/SELL), M1_TRIGGERED, ENTRY_WINDOW (up to 5 M1 bars after the trigger close, close within 0.25 ATR5 of the trigger close), MISSED (close beyond 0.5 ATR5 from the trigger close before entry), INVALIDATED (close below `zone.low - 0.25 ATR5`; SELL mirrored), FAILED_CONFIRMATION (after M5 confirmation, an M5 close beyond the zone invalidation before any M1 trigger), EXPIRED (window ended).

## Hypothetical entry, exits and costs
- Entry: fill at the OPEN of the M1 bar after the trigger bar (never the trigger bar), ask-aware for BUY, bid for SELL; spread = last closed M1 bar's spread (the stored spread is unreliable, so fixed-spread floors 0.2 / 0.4 USD are mandatory sensitivity, plus slippage 0 / 0.1 / 0.3).
- SL: `min(trigger bar low, zone.low) - 0.25 ATR5` (SELL mirrored); TP: the V1 impulse target when a V1 setup is active, otherwise 2.0 x the stop distance; the same `risk-1` plan checks and `gate-1` (net R:R >= 1.5 after costs, broker stops level 6.00, spread/ATR limit) on the REFERENCE account (privacy mode). Timeout 288 M1 bars.
- One open hypothetical position per direction; one trade per (zone, direction, trigger bar).

## Evaluation (only after the minimum sample; frozen now)
Net expectancy per trade in R with a 95% day-block bootstrap interval (2000 resamples, seed 20261014), win rate, profit factor, max drawdown (R), by direction / trigger type / hour; cost sensitivity; signal funnel (context -> zone -> M5 confirmed -> M1 triggered -> risk-OK -> filled -> outcome). Comparators on the same forward period: B0 no trade; B1 V1 (`cand-1`) trades in the same period; B2 random M1 entries with the same stop/target geometry (500 seeds). V2 "shows evidence" only if: >= 100 triggered and filled trades, mean R > 0 at base cost and at +0.3 slippage and at the 0.4 spread floor, bootstrap lower bound > 0, above the 95th percentile of B2, positive in at least 3 of 4 chronological quarters of the forward period, no single week contributing more than 40% of total R. Otherwise INSUFFICIENT_EVIDENCE or NO_EVIDENCE_OF_EDGE. No threshold above may be changed after the first forward outcome is looked at; a change is a new version (V3) with its own registration and clock.

## Guards
- Lookahead: prefix-invariance (state at time t equals state with all later bars removed or corrupted) on synthetic data, mutation-checked; closed-bar-only; the forming bar never enters an event.
- Mirror: SELL is the exact mirror of BUY (tested).
- Determinism: same bars => identical event list (hash).
- Shadow: `v2_*` fields live in their own payload section; V1 `decision` is byte-identical with and without V2 (tested).
- Logging is append-only and contains only market data and decision-time evidence (no account figures).

## Limits known in advance
Few M15 zones, an M5 confirmation and an M1 trigger all together are rare: the 100-trigger minimum may take many weeks; one instrument and feed; spread data quality; M1 history limited by the terminal; forward results describe the future period only.
