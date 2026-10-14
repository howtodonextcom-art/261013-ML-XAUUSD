# Interactive browser QA through an MCP (2026-10-14)

Honest scope. FIXTURE PASS = the page's real renderer driven by an explicitly labelled SYNTHETIC scenario (tests/e2e/mcp_fixture_injector.js); LIVE = the real MetaQuotes-Demo gateway.

## Tooling
- Playwright MCP: configured (user scope) but its browser `chrome-for-testing` is NOT installed (tool error: "Browser chrome-for-testing is not installed"); not used, nothing recorded as passed through it. Fix: `npx @playwright/mcp install-browser chrome-for-testing`, or add `--browser chrome --isolated` to its arguments.
- Chrome DevTools MCP: connected, drives real Google Chrome with an isolated profile (not the user's profile). Real MCP clicks, `navigate_page`, `emulate` (viewport / device pixel ratio), `take_snapshot`, `take_screenshot`, console and script evaluation worked.
- The automated Playwright suite (48 tests, Chrome 155, channel chrome) is separate and is not a substitute for this interactive session.

## Results
| Mandatory scenario | Status | Evidence |
|---|---|---|
| 1 WAIT, no direction | FIXTURE PASS | WAIT, `NO_DIRECTION [market reason]`, next required text, no plan, no lines |
| 2 WAIT, awaiting pullback | FIXTURE PASS + LIVE VERIFIED (state observed live: AWAITING_PULLBACK with H1 DOWN / H4 DOWN) | live panel in the first screenshot |
| 3 WAIT, awaiting confirmation | FIXTURE PASS | AWAITING_CONFIRMATION, zone lines only, no entry/SL/TP |
| 4 BUY eligible, Entry/SL/TP | FIXTURE PASS; LIVE NOT OBSERVED | BUY, plan + lot + risk %, 5 backend lines; label "paper plan · hypothetical · no order is sent" |
| 5 SELL eligible, mirrored levels | FIXTURE PASS; LIVE NOT OBSERVED | SELL, SL above entry, TP below; QA found the BUY-worded next-event sentence on SELL setups (FIXED, test) |
| 6 eligible but BLOCKED | FIXTURE PASS | BLOCKED (amber), "NOT ELIGIBLE · HYPOTHETICAL LEVELS ONLY (no size is shown)", dashed grey lines titled NOT ELIGIBLE, no lot |
| 7 INVALIDATED / MISSED | FIXTURE PASS + LIVE VERIFIED | live panel listed real events "SELL CONFIRMED -> INVALIDATED (INVALIDATION_LEVEL_TOUCHED)" |
| 8 DATA_STALE + interrupted WebSocket | FIXTURE PASS (stale) ; websocket loss covered by the Playwright suite (F6), not re-done by hand | STALE badge, reasons kept, plan/setup blank, no lines |
| 9 reconnect without duplicate candles | NOT DONE by hand; Playwright connection tests cover it (fixture/live) | |
| 10 rapid timeframe switching while intel updates | LIVE VERIFIED | 5 real MCP clicks M5,H4,M15,H1,M1 in a row: ended on M1 with M1 data, 2001 bars, 0 duplicate times, 0 paint errors, 0 console messages |

| Viewport | Status | Evidence |
|---|---|---|
| 1440x900 (window 1919x889 in practice) | PASS | decision card, plan and reasons visible next to the chart, no horizontal scroll |
| 1152x720 | PASS | card 300x524 at y=53, everything above y=577, chart 807x490, no horizontal scroll |
| 390x844 (DPR 3, mobile emulation) | FIXED then PASS | before: chart 574 px high pushed the action badge to y=761 (barely visible); after limiting the chart to 38vh on narrow screens: badge at y=508, primary reason at 563, no horizontal scroll |
| Browser zoom 125/150/200% | NOT TESTED natively | only device-pixel-ratio emulation exists in the tooling; CDP key events do not trigger Chrome's native zoom |

Not covered: drawing tools (not implemented), accessibility audit, keyboard-only operation, real ENTRY_ELIGIBLE on live data (none occurred during the session), levels of fixture scenarios are far from the live price so they are off-chart in MCP screenshots (pixel positions are verified in the Playwright suite with live-price-relative levels).

Screenshots are kept locally in qa-artifacts/ (git-ignored); none contains account data (the decision payload never carries it).
