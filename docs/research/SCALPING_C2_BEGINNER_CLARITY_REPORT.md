# Level 6.5.2: C2 beginner clarity, risk semantics and UI acceptance (RESEARCH BETA, SHADOW, PAPER)

Mode: READ_ONLY + SHADOW + PAPER_SIMULATION. No MT5 order function is called. Registered strategy, thresholds and fill model were not changed. The sealed holdout was not opened. V1, V2 and the forward logs are unchanged by this level.

## 1. Paper risk forensic audit (P0): what "passed" really checked

Path: `build_c2_view` -> `plan_direct` (backtest/engine.py) -> `gate_checks` (decision/decide.py) + `plan_trade` (decision/risk.py).

| Item | Checked? | How |
|---|---|---|
| Planned entry | assumed | the closed trigger bar close on the bid chart (identical to the registered evaluator `plan_for`) |
| Registered fill | NOT in the preflight | next M1 bar open; shown as `expected_fill` only once that bar exists, never for history |
| Current Bid/Ask vs entry | **not checked before 6.5.2** | now a display-time comparison (`quote_check`) |
| Spread / ATR limit | yes | `gate_checks`, with the live spread of the latest tick on every refresh (0.30 ATR) |
| Slippage | modelled | 0.5 x spread allowance inside `plan_trade` net R:R; not a live measurement |
| Broker stops level | modelled | `XAU_SPEC.stops_level_points` 600 points = 6.00 USD, a fixed spec in the engine, not read per account at this call |
| Net R:R minimum | yes | 1.5 after modelled costs |
| Equity, margin, lot | **hypothetical** | `HYP_EQUITY` 100,000 and a fixed XAUUSD spec; not the real account, margin or limits |
| Data age | **assumed fresh** | `data_age_s=0.0` is hard-coded in `plan_direct`; the staleness protection is the DATA_STALE strip of the whole section (payload level) |
| Market open | **assumed open** | `market_open=True` hard-coded in `plan_direct` |
| Daily loss limit | not configured | `None` by policy |
| Entry band and expiry | yes, closed bars | stage ENTRY_WINDOW vs M1_TRIGGERED and the 5-minute window (clock based) |

Conclusion: "PASSED Risk Gate" overstated what was verified. It was a paper preflight on a reference account. It is now **PAPER PREFLIGHT PASSED** and states that the live quote and the real account are NOT verified. "Actual execution readiness: NOT VERIFIED" is always shown.

New in this level (display-time, from registered numbers only, no new trading condition): `quote_check` compares the live quote with the plan: IN_BAND, DRIFTED (bid beyond the registered 0.25 ATR5 entry band in the trade direction), BEYOND_STOP (bid beyond the planned stop), QUOTE_STALE (older than the 10 s gate age). DRIFTED / BEYOND_STOP / QUOTE_STALE remove the paper signal and plan from the current state ("NOT CURRENT") and from the chart markers.

## 2. Design options (P3), chosen before building

| Option | Idea | Verdict |
|---|---|---|
| A | one-line explanation under the signal + collapsible SIGNAL DETAILS + collapsible dictionary inside the card | **chosen**: chart-first, nothing added to the first screen except one line |
| B | modal glossary opened by a "?" button | rejected: hides the meaning behind a click, adds a focus trap |
| C | tooltips only | rejected: invisible on touch, not readable at a glance |

## 3. UI before / after
- Before (6.5.1): seven fields; "PASSED Risk Gate"; title "XAUUSD Terminal (slice 1)"; BLOCKED amber; trigger candidate purple; no countdown, no quote comparison, no dictionary.
- After: seven fields kept; label "simulated, after paper preflight"; one plain-language line (Vietnamese); BUY research green, SELL research red, C2 PAPER purple, BLOCKED orange, WAIT grey, HISTORICAL light grey; SIGNAL DETAILS (strategy/version, state, side, trigger close time, analysis/published/received times, provenance, expiry + countdown, planned entry/SL/TP, net R:R, current Bid/Ask and difference, expected simulated fill, reference-account warning, readiness NOT VERIFIED); dictionary "Hiểu tín hiệu"; title "XAU/USD Scalping Intelligence · Research Terminal".

## 4. Signal dictionary (shown in the UI, Vietnamese)
WATCH -> M1 TRIGGER -> ENTRY WINDOW -> C2 BUY/SELL PAPER or BLOCKED -> EXPIRED (and HISTORICAL). Each entry answers: what happened, what is missing, is it a real decision, is it still valid, what to check before a human decides. C2 BUY PAPER: "Đây là tín hiệu mô phỏng sau kiểm tra rủi ro tham chiếu, không phải lệnh mua hoặc xác nhận giá hiện tại có thể khớp." V1 Decision / V2 Shadow / C2 Research are explained as three separate research layers.

## 5. Safety and event accuracy (P4)
Expired window -> "WINDOW_ELAPSED" / EXPIRED (never ENTRY WINDOW). Price out of band, beyond stop, stale quote -> NOT CURRENT. Spread is re-evaluated each refresh. Stale or disconnected feed -> the whole C2 section is stripped (verified in real Chrome: TRANSPORT_STALLED showed "stale: no scalping observation", no plan, no detail rows, and it recovered to CONNECTED_ACTIVE). Historical triggers show no fill figures. A paper or BLOCKED marker replaces the plain trigger marker of the same bar; an expired live trigger is drawn muted as "C2 trig (expired)".

## 6. Limitations
- A live PAPER BUY/SELL is still rare: the fixtures cover PAPER BUY/SELL, BLOCKED, EXPIRED, DRIFTED, HISTORICAL; fixtures are not live observations. A live paper signal was observed once earlier (Level 6.5.1), not during this level's final check.
- The reference spec (stops level 6.00 USD, hypothetical equity) is fixed in the engine; the real broker or account may differ.
- `plan_direct` still assumes data age 0 and market open; the protection is the payload-level stale strip. Not changed, because changing the registered gate would alter C2 semantics.
- The countdown relies on the server tick time and a 15 s trust window.
- Evidence still requires >= 100 triggers and 30 days; a paper signal is not a profit claim.
