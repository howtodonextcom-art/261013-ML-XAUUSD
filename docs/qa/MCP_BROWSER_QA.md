# Interactive browser QA through an MCP (2026-10-14)

Honest scope. FIXTURE PASS = the page's real renderer driven by an explicitly labelled SYNTHETIC scenario (tests/e2e/mcp_fixture_injector.js); LIVE = the real MetaQuotes-Demo gateway.

## Tooling
- Playwright MCP: configured (user scope) but its browser `chrome-for-testing` is NOT installed (tool error: "Browser chrome-for-testing is not installed"); not used, nothing recorded as passed through it. Fix: `npx @playwright/mcp install-browser chrome-for-testing`, or add `--browser chrome --isolated` to its arguments.
- Chrome DevTools MCP: connected, drives real Google Chrome with an isolated profile (not the user's profile). Real MCP clicks, `navigate_page`, `emulate` (viewport / device pixel ratio), `take_snapshot`, `take_screenshot`, console and script evaluation worked.
- The automated Playwright suite (59 tests, Chrome 155, channel chrome) is separate and is not a substitute for this interactive session.

## Results
| Mandatory scenario | Status | Evidence |
|---|---|---|
| 1 WAIT, no direction | FIXTURE PASS | WAIT, `NO_DIRECTION [market reason]`, next required text, no plan, no lines |
| 2 WAIT, awaiting pullback | FIXTURE PASS + LIVE VERIFIED (state observed live at that time: AWAITING_PULLBACK with H1 DOWN / H4 DOWN; since Level 6.2 a WAIT without any setup is labelled NO_VALID_IMPULSE) | live panel in the first screenshot |
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


---

# Level 5.1 session (2026-10-14, later): authenticated UI through the Chrome DevTools MCP (real Google Chrome, isolated profile)

Tool: Chrome DevTools MCP (the Playwright MCP's browser is still not installed). Real MCP clicks on accessibility-tree uids, real key presses, `emulate`, `navigate_page`, snapshots, console, network. FIXTURE = labelled synthetic scenario; LIVE = real MetaQuotes-Demo gateway.

| Check | Status | Evidence |
|---|---|---|
| Unauthenticated visit | LIVE VERIFIED PASS | `GET /` shows only "Authentication required..." (no data, no controls) |
| Token URL login | LIVE VERIFIED PASS | page loads, URL becomes `/` (token gone), `document.cookie` is empty (HttpOnly cookie), live data flows |
| Gateway stopped | LIVE VERIFIED PASS | state DISCONNECTED, decision badge STALE, plan/setup/events text blank, 0 chart lines, price marked stale, banner shown |
| Gateway restarted | LIVE VERIFIED PASS | reconnected within 2 s, new `seq` (wall-clock ms), 2000 bars, 0 duplicate times, no STALE badge; the session cookie survived the restart (HMAC of the persistent token) |
| Console on disconnect | NOTE | one connection-refused error per reconnect attempt (20 in about 40 s before the back-off was added; now 1 s growing to 5 s) |
| Drawing: H-line | LIVE VERIFIED PASS | MCP click on the H-line button then on the chart (accessibility role "application"): 1 drawing at the clicked price, selected, tool back to Select, Undo enabled |
| Drawing: trendline guard | LIVE VERIFIED PASS | two MCP clicks on the same point: refused with the hint "pick a different bar..."; Escape cancels |
| Drawing: Delete / Undo / persistence | LIVE VERIFIED PASS | real keys Delete (removed), Ctrl+Z (restored, Redo enabled), reload (drawing still there from localStorage) |
| Drawing: drag precision, zone, redo, clear | Playwright only | real mouse events with pixel checks (tests/e2e/drawings.spec.ts, 11 tests); the MCP offers click-by-element, not coordinates |
| Native browser zoom 100/125/150/200% | NOT TESTED | Ctrl+= through the DevTools protocol does not change the browser zoom (devicePixelRatio stayed 1); only EMULATED (viewport + DPR): 1152x720@1.25, 960x600@1.5, 720x450@2 had no horizontal overflow; at 720x450 the badge was below the fold, fixed by placing the decision card before the chart below 900 px |
| 1440x900, 1152x720, 390x844 | PASS (live + Playwright) | no horizontal scroll; decision card and reason visible without scrolling |
| BUY/SELL on live data | NOT OBSERVED | no eligible setup occurred; BUY/SELL verified with labelled fixtures only (Playwright, visual regression, MCP injector) |
