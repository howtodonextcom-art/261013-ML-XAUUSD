# V1 signal forensics (Level 6.2): why the terminal says WAIT so often

Written 2026-10-14. Data: development + validation history (M15/H1/H4 bars closed at `val_end` = 1785643200, 2025-10-14 .. 2026-08-02, strategy `cand-1[setup-1+risk-1+gate-1]`, dataset `ds-0.2`). The sealed holdout was NOT loaded (`holdout_loaded: false` in the result). Reproduce: `.\.venv\Scripts\python.exe benchmarks\v1_signal_funnel.py` -> `results/v1/signal_funnel.json`. This is a historical replay, not forward evidence and not live observation. No threshold was changed.

## 1. Production path audited
MT5 -> closed bars M15/H1/H4 -> `compute_heavy` (direction H1, conflict H4, setup-1 state machine on M15) -> `make_decision` (`decide()` with risk-1 and gate-1 on the reference account) -> payload -> WebSocket -> UI. The heavy analysis is recomputed when an M15/H1/H4 bar closes (event) and at the latest every 120 s; the decision is refreshed every 2 s from the cached analysis with the current bid, spread, data age and risk.

## 2. Finding 1: a labelling defect (fixed, no behaviour change)
`current_status()` returned `AWAITING_PULLBACK` whenever there was NO active setup but H1 had a direction. That wrongly told the human that a setup existed and was waiting for its pullback. Nothing was actually waiting: no qualifying impulse leg was on the books. Since Level 6.2 this case is `NO_VALID_IMPULSE`; `AWAITING_PULLBACK` now means exactly an active `SETUP_FORMING` setup. The decision (WAIT), the thresholds and every backtest result are unchanged (only the text and the reason code of the WAIT). Definitions (all other codes unchanged):

| WAIT reason | Meaning |
|---|---|
| NO_DIRECTION | H1 shows no direction |
| NO_VALID_IMPULSE | a direction exists, no qualifying impulse leg (>= 1.5 ATR) is active |
| AWAITING_PULLBACK | SETUP_FORMING: impulse found, waiting for a pullback of >= 0.5 ATR |
| PULLBACK_IN_PROGRESS / NO_RELEVANT_ZONE | pulling back, not at / no confirmed zone |
| AWAITING_CONFIRMATION | at the zone, no closed confirming bar yet |
| ENTRY_WINDOW_NOT_OPEN | confirmed, price not inside the entry band yet |
| SIGNAL_CONFLICT, INSUFFICIENT_HISTORY, DATA_STALE | as before |
Terminal outcomes (MISSED / INVALIDATED / EXPIRED) are setup events, listed in the history panel; the WAIT after them is NO_VALID_IMPULSE (or the reason of the next setup). BLOCKED is a separate action (eligible setup stopped by risk-1 / gate-1).

## 3. Finding 2: the funnel (development + validation, 6.5 months, 18,409 M15 bars)
Context: 54.5% of M15 bars have no usable H1 direction (NONE/UNKNOWN), 23.3% UP, 22.2% DOWN, 2.3% H4 conflict.

| Stage (unique setup ids) | BUY | SELL |
|---|---|---|
| bars with a usable context and no H4 conflict | 4,175 | 3,775 |
| impulse (SETUP_FORMING) | 177 | 167 |
| pullback | 173 | 159 |
| zone | 128 | 135 |
| confirmation | 49 | 51 |
| entry window | 30 | 23 |
| ENTRY_ELIGIBLE | 29 | 33 |
| risk PASS = decision published BUY/SELL | 10 | 21 |
| risk BLOCKED | 19 | 12 |

Terminal states: BUY expired 71 / invalidated 91 / missed 15; SELL expired 49 / invalidated 103 / missed 15. Top terminal reasons: `INVALIDATED:ZONE_FAILED` (BUY 46 / SELL 60), `EXPIRED:SUPERSEDED_BY_CONTINUATION` (BUY 28), `INVALIDATED:STRUCTURE_BROKEN` (26 / 23), `EXPIRED:CONFIRMATION_TIMEOUT` (24 / 15), `EXPIRED:ENTRY_WINDOW_ENDED` (16 / 23), `MISSED:PRICE_RAN_AWAY` (SELL 15). Blocking reasons: `RISK:RR_TOO_LOW` (BUY 10 / SELL 9) and `RISK:SL_TOO_CLOSE` (BUY 9 / SELL 3; the 6.00 USD broker stops level). 88.0% of M15 bars have no active setup of any direction (323 stretches, median 22 bars = 5.5 h, longest 910 bars = 9.5 days).

## 4. Conclusion: policy constraint, not starvation by bug
V1 publishes a BUY or SELL roughly 31 times in 6.5 months (about one per week), because (a) more than half of the time there is no H1 direction, (b) 177 / 167 impulse setups shrink to 29 / 33 entry-eligible ones (zone and confirmation rules), and (c) the risk gate blocks 31 of the 62 entry-eligible setups (50%). A long run of WAIT is therefore the normal behaviour of the frozen policy, plus one misleading label (finding 1, fixed). Whether the policy is too strict is a RESEARCH question: it is not answered by this report and no threshold was changed. 7 validation trades (P6) remain INSUFFICIENT_EVIDENCE.

## 5. Research proposal only (NOT implemented): momentum / breakout opportunities
The funnel shows 15 MISSED setups per side ("price ran away") and, for BUY, 28 `SUPERSEDED_BY_CONTINUATION` expiries: moves that continued without the pullback the setup waits for. A separate pre-registered study could ask whether a breakout/momentum candidate has positive expectancy after costs on NEW forward data. Requirements before any code: new pre-registration (hypothesis, causal `known_at`, costs, baseline = V1 and random), separate dataset version, forward-only evidence (the stored M1 history is inside the sealed holdout period), shadow only, never merged into V1.

## 6. Update frequency and latency (measured on this PC, 2026-10-14)
| Layer | Cadence / cost |
|---|---|
| tick -> browser | every tick; gateway p50/p99 about 1 / 7 ms (docs/qa/LATENCY_REPORT.md) |
| chart candle paint | coalesced to one repaint per animation frame |
| heavy strategy recompute | on every M15/H1/H4 bar close, fallback 120 s; 220 ms median, 520 ms p95 for the production window (3000 M15 bars), in a worker process |
| decision refresh (bid, spread, risk) | every 2 s, 0.01 ms per refresh |
| decision publication latency | each V1 event stores `publish_latency_s = published_at - known_at` (1 s resolution, server time): the delay between the closed bar that made the setup knowable and the moment the decision was first published |
A closed-bar confirmation is never re-evaluated before the bar closes; M1 price movement between M15 closes changes only the current bid, spread and risk of an already confirmed setup, never the setup itself.
