# SETUP LIFECYCLE (P4): Multi-Timeframe Trend Pullback + relevant zone + price-action confirmation

Package `services/intelligence/xau_intel/setups` (policy versions: `setup-1`, `pa-1`, `zone-1`, `dir-1`). Pure functions of CLOSED bars; no tick, no network, no MT5. It describes the state of a setup; **it does not issue BUY/SELL** (that is P5) and it makes no claim that any setup is profitable.

## Inputs (all causal)
- Setup timeframe bars (default M15) and the confirmed zig-zag swings of that timeframe (k = 2.5, window-start artifact excluded).
- Per-bar direction context from a higher timeframe (default H1): `UP` if structure UP and EMA50 slope > 0 and close above EMA200 (DOWN mirrored); `NONE`; `UNKNOWN` until EMA200 exists (INSUFFICIENT_HISTORY). A higher timeframe bar is visible to a setup bar only after it has closed (`align_to`).
- Optional per-bar conflict flag (an even higher timeframe, default H4, opposes the context). A conflict blocks the creation of new setups; it does not cancel existing ones.

## States
`SETUP_FORMING -> PULLBACK_IN_PROGRESS -> AT_RELEVANT_ZONE -> AWAITING_CONFIRMATION -> CONFIRMED -> ENTRY_WINDOW <-> ENTRY_ELIGIBLE`; terminal `INVALIDATED`, `MISSED`, `EXPIRED`. No active setup = NO_SETUP. BLOCKED is a P5 gate state, not a setup state.
| Transition | Rule (BUY view; SELL is the exact mirror) |
|---|---|
| create `SETUP_FORMING` | context UP, no conflict, a confirmed swing high not yet used and confirmed at most 20 bars ago, an earlier confirmed swing low, leg >= 1.5 ATR, and close not above the high |
| -> `PULLBACK_IN_PROGRESS` | low is >= 0.5 ATR below the impulse high |
| -> `AT_RELEVANT_ZONE` | a zone (>= 2 confirmed swings within 0.5 ATR, padded 0.25 ATR) lying below the impulse high and above the impulse start is touched (`low <= zone.high`) without a close below `zone.low` |
| -> `CONFIRMED` | at the zone, up to 5 bars after the touch bar (inclusive; timeout is declared on the 6th): a bullish pin bar / engulfing / strong close (pa-1) whose low reaches into the zone (`low <= zone.high`), does not pierce more than 0.25 ATR below it, and whose close is above `zone.low` (a pattern bar floating above the zone does not confirm) |
| `CONFIRMED` data | planned entry = confirmation close; invalidation = min(confirmation low, zone low) - 0.25 ATR; window = 4 bars; band = 0.25 ATR; chase limit = 1 ATR |
| `ENTRY_WINDOW` / `ENTRY_ELIGIBLE` | window open; eligible while close <= entry + band (flips back to ENTRY_WINDOW when price leaves the band) |
| `INVALIDATED` | `ZONE_FAILED` (close below zone low - 0.25 ATR), `STRUCTURE_BROKEN` (close below the impulse start), `CONTEXT_LOST` (before confirmation only), `INVALIDATION_LEVEL_TOUCHED` (low <= invalidation after confirmation) |
| `MISSED` | `PRICE_RAN_AWAY`: high exceeds entry + 1 ATR before price was ever inside the band |
| `EXPIRED` | `SUPERSEDED_BY_CONTINUATION` (close above the impulse high), `CONFIRMATION_TIMEOUT`, `ENTRY_WINDOW_ENDED`, `SETUP_AGE` (60 bars counted from the bar at which the impulse high became known) |
Events are emitted only on a state change, so one situation never produces repeated setups. `setup_id = <tf>-<BUY|SELL>-<impulse high known_at>-<impulse start price>` is stable across recomputation. Every event carries `known_at` (= close of its bar), `evaluated_at`, evidence list, invalidation level, next required event, policy version and reason codes.

## WAIT reasons (`current_status`)
NO_DIRECTION, NO_RELEVANT_ZONE, AWAITING_PULLBACK, PULLBACK_IN_PROGRESS, AWAITING_CONFIRMATION, SIGNAL_CONFLICT (both directions active, or a higher-timeframe conflict with no setup), ENTRY_WINDOW_NOT_OPEN, INSUFFICIENT_HISTORY, DATA_STALE. Layers: market reason (context, history), strategy reason (setup state), gate reason (spread, staleness; P5).

## Evidence (tests/unit/test_setups.py and test_setups_review.py, 47 tests; `scripts/windows/setup_demo.py`)
Hand-built scenario through every state with exact bar indices; each terminal reason; BUY/SELL exact mirror on the scenario AND on 8 whole random markets seen upside down (200 - price: states, bars, reason codes, levels, positive real prices in the evidence text); transitions legal on 6 random markets, `prev_state` chain consistent, never repeat after a terminal state; events never exceed one per transition; **prefix equals full** (no future information) on 4 seeds with sliced context and on 3 seeds through the FULL pipeline (higher-timeframe direction and alignment recomputed from truncated data); 24 random markets reach every state and every terminal reason (the property tests are not vacuous). Five mutations (zone-touch rule removed, unsigned SELL evidence, age from creation, no impulse-age limit, conflict ignored) each make exactly one regression test fail.
Real data, descriptive only (M15, 120 days, H1 direction, H4 conflict): 131 setups, 124 pullbacks, 100 at a zone, 30 confirmed, 20 reached ENTRY_ELIGIBLE, 7 missed; terminal reasons dominated by ZONE_FAILED (43) and SUPERSEDED_BY_CONTINUATION (24). Compute 0.18 s.
Independent review (docs/qa/RED_TEAM_FINDINGS.md, round 4) found and the fixes closed: confirmation without touching the zone, SELL evidence printed in mirrored prices, wrong `prev_state` on the first event, setups created long after their impulse, an H4 conflict ignored once a setup was active.
Design notes confirmed by the reviewer: MISSED uses the bar HIGH (price may have touched the chase limit intrabar even if it closed inside the band, so entry cannot be assumed); a conflict does not cancel an existing setup but removes entry readiness while it lasts.

## Limits (honest)
- All thresholds are initial design parameters derived from the definitions; **none were validated or tuned**, and no outcome (profit, win rate) has been measured. The 28% confirmation rate says nothing about edge.
- Confirmation uses only candle patterns at the zone; the 4 pattern definitions are conventional quantifications, not evidence that they predict.
- Zones come from swings only (no EMA or volume zones). Relevance is "between the impulse start and high"; there is no distance-to-price filter.
- Fills are not simulated here (P5/P6). Entry = confirmation close is a proxy.
- Only the M15/H1/H4 combination has been run; M5/M1 timing and other combinations are not evaluated.
- Not wired to the live gateway or dashboard yet.
