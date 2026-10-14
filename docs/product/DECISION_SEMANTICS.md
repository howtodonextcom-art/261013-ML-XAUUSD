# Decision, alert and state semantics (Level 6.4)

Exact meaning of every state, from the code, with timeline evidence from the production path (`compute_heavy` -> `make_decision` -> `v1_event_from_decision`) on historical fixtures (not live). Four layers that must never be mixed: market bias, setup status, V1 decision, V2 shadow.

## 1. The four layers
| Layer | Values | Source | May it create BUY/SELL? |
|---|---|---|---|
| Market bias | BULLISH / BEARISH / NEUTRAL / UNKNOWN | H1 direction and H4 conflict from the backend (`market.direction`, `conflict`) | **No**: a display of context; the UI mapping predicts nothing |
| Setup status | F forming (SETUP_FORMING) / C confirmed (CONFIRMED) / M missed / X expired / I invalidated, plus intermediate pullback, zone, waiting, entry window, eligible | setup-1 state machine on closed M15 bars | No: a setup is a precondition, never a decision |
| V1 decision | BUY / SELL / WAIT / BLOCKED | `decide()` with risk-1 and gate-1 | Yes: the only source of BUY/SELL |
| V2 shadow | observation only | M1 shadow candidate | No: `execution_authorized: false`, separate panel and markers |

## 2. When does the backend say BUY or SELL?
All of: (1) an active setup reached ENTRY_ELIGIBLE on a CLOSED M15 bar (pullback to a confirmed zone, closed confirming bar, entry window open, price inside the entry band, not past the chase limit); (2) no H4 conflict and no second opposing setup; (3) the paper plan is valid with the CURRENT bid, spread and ATR (risk-1: stop at least the broker stops level 6.00 USD away, net R:R at least the minimum after costs, reference-account budget); (4) the hard gates pass (spread/ATR limit, data age at most 10 s, market open inferred from tick flow, daily-loss limit if configured); (5) the data is fresh. If (1) and (2) hold but (3) or (4) fail the action is BLOCKED (with the failing code); if (1) fails it is WAIT with the reason of the missing condition. Market bias is never an input to any of this.

## 3. When is it published, recorded and shown?
| Moment | Mechanism |
|---|---|
| eligible | the closed M15 bar that completes the setup (`known_at`, server time) |
| re-evaluated | the heavy analysis on every M15/H1/H4 bar close (event wake-up, fallback 120 s); the decision with the current bid/spread/risk every 2 s |
| published | `publish_intel` (atomic) -> WebSocket; the V1 event (`published_at`, `known_at`, `publish_latency_s`) is stored BEFORE publication, first publication per (setup, action) only |
| shown | the next animation frame after receipt (9 to 16 ms measured); toast on a NEW event; sound and desktop notification only if the user opted in |
| not actionable any more | BLOCKED/WAIT on any refresh; the setup is terminal (MISSED / EXPIRED / INVALIDATED) at the first bar that closes after the condition; payload older than 10 s is served as DATA_STALE by the backend itself; the browser clears levels and markers after 10 s without frames or on disconnect (`TRANSPORT_STALLED` flag after 4 s) |
| stored | `data/decisions/v1_events.jsonl` (append-only, durable, deduplicated, no account data); setup events: live engine plus deterministic replay, served by `/api/setup_events` |
`setup.expires_at` and `entry_window_ends_at` are informational (bar-count rule); the setup actually ends at the first closed bar after them. A marker is always history; only `NOW` marks the decision that is valid at this moment.

## 4. Alerts: what exists
Before Level 6.4: visual only (state change announced to screen readers, no toast, no sound, no notification). Now: a toast for every NEW V1 event (BUY, SELL, BLOCKED) in the browser session, never for history present at load; a short sound and a desktop notification for NEW BUY/SELL only, both OFF by default and opt-in via the header buttons; BLOCKED never sounds. The toast always says "a research observation, not an order, not advice".

## 5. Timeline evidence (production path on historical fixtures; times are server time)
| Scenario | Result | Setup | Setup known (closed M15 bar) | Window | Expires |
|---|---|---|---|---|---|
| SELL published | SELL, ENTRY_ELIGIBLE, net R:R 4.97 | M15-SELL-1761655500-4019.75 | 2025-10-28 18:15:00 | entry window ends 19:00:00 | 2025-10-29 03:45:00 |
| BUY published | BUY, ENTRY_ELIGIBLE, net R:R 2.85 | M15-BUY-1762542900-3984.32 | 2025-11-07 19:45:00 | ends 20:30:00 | 2025-11-08 10:15:00 |
| BUY blocked | BLOCKED, `RISK:SL_TOO_CLOSE: 5.71 < broker stops level 6.00` | M15-BUY-1764664200-4191.11 | 2025-12-02 09:45:00 | ends 10:15:00 | 2025-12-02 23:30:00 |
In all three the event id is `setup_id|action[|reason]`, one event however many refreshes follow (tests: 40 repeated frames and a restart give one record). Live: **no BUY/SELL has been observed since the event log exists**; the chain above is verified on replays and fixtures only.
