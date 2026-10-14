# BROWSER TEST MATRIX

Tool: Playwright 1.64.0 (`@playwright/test`, pinned in package.json) driving **Google Chrome 155.0.8059.40 (channel `chrome`, headed)**; user agent contains `Chrome/155.0.0.0` and not `HeadlessChrome` (captured in `qa-artifacts/smoke/chrome.txt`). Throw-away browser profile (Playwright default), never the personal profile. Target `http://127.0.0.1:8765` (live gateway on MetaQuotes-Demo). Run: `npx playwright test` (gateway must be running; connection tests stop/restart it and restore it).

Result of the last two full runs: **59 passed, 0 failed, 0 skipped** (about 75 s). One earlier full run had 1 unexplained failure (BUG_FIX_LOG O1).

| Gate item | Spec | Assertions that give it meaning | Status |
|---|---|---|---|
| F1 toolchain | smoke.spec | real Chrome UA, screenshot, click with `aria-pressed` effect, Tab/Enter keyboard, viewport change verified by `innerWidth`, console capture, websocket frames received, aborted request detected | VERIFIED PASS |
| F2 control coverage | inventory.spec | every interactive DOM element has a testid and an inventory entry (test fails on an unknown control); every button clicked and its state asserted; doc regenerated from the DOM | VERIFIED PASS for the 6 existing controls (UI_CONTROL_INVENTORY.md) |
| F3 timeframes | timeframes.spec (8) | per TF: bars on the TF grid (`t % sec == 0`), min spacing >= TF, OHLC sane, history length (M1/M5 >= 1000, M15/H1 >= 500, H4 >= 250), last 50 closed bars equal `/api/candles`, other buttons unpressed; M1->M5->M1 restores 60 s spacing; 7 rapid clicks end on the last click; failed request clears chart + banner | VERIFIED PASS |
| F3 chart interaction | chart.spec (4) | wheel zoom in/out changes visible range in the right direction; drag pans by distance without rescaling; crosshair time is a real bar time and price within data range; refresh/live ticks do not move the user's range | VERIFIED PASS |
| F4 responsive | chart.spec resize + responsive.spec (11) | zoom 67/80/100/125/150/200% (emulated, see below), 1440x900, 1152x720, 1920x1080, 390x844 @dpr2, 1440x900 @dpr2: no horizontal overflow, 5 TF buttons visible with >= 20 px targets, status and bid visible, chart width/height sane, sidebar does not overlap chart, no clipped text | VERIFIED PASS (2 screenshots also reviewed by eye: mobile and 200%) |
| F5 decision panel | decision.spec (11) | backend records WAIT / BUY / SELL / BLOCKED / stale injected through the page's real websocket handler: action, primary reason + layer, eligibility, plan numbers, evidence, next required event, versions, EXECUTION NOT AUTHORIZED; levels drawn at the right PIXEL positions (TP above entry above SL); BLOCKED that carries a plan is not shown as BUY; stale decision dims and removes its levels after 10 s; HTML in server text is escaped; live backend record equals the DOM and contains no account figures | VERIFIED PASS (4 UI mutations each break a test) |
| F5 connection | connection.spec (2) | gateway killed -> DISCONNECTED within 15 s, banner, price struck through and frozen for 2.5 s, restart -> CONNECTED_ACTIVE, no duplicate bars, history intact; websocket silent -> TRANSPORT_STALLED < 9 s, then recovery | VERIFIED PASS |

## Browser zoom
Chrome's native Ctrl +/- cannot be delivered through CDP. Zoom z on a 1440x900 window is **emulated** with an equivalent context: CSS viewport (1440/z) x (900/z) and devicePixelRatio z (asserted). The layout the page sees is the same; browser chrome (tab strip, scrollbar styling) is not exercised.

## Mutation evidence (tests can fail)
Serving M5 data for the M1 request, and truncating M5 history to 3 bars, both make the timeframe assertions fail (throw-away spec, not kept).

## Not implemented / NOT TESTED (nothing is claimed)
- Interactions: double-click, right-click, hover tooltips, drag-and-drop, Back/Forward, keyboard shortcuts (none defined), undo/redo, menus and dialogs: no such controls exist or not exercised.
- Drawing tools (horizontal line, trendline, zones, rectangle, entry/SL/TP, R:R), indicator toggles, replay controls, risk settings, strategy selector: **NOT IMPLEMENTED** (P8 scope).
- Visual regression with deterministic data states: **NOT IMPLEMENTED** (screenshots are saved to `qa-artifacts/`, not pixel-diffed).
- High-tick-rate deterministic replay, sleep/resume, DevTools performance (frame drops, memory, listener leaks), tab inactive, memory pressure: **NOT TESTED**.
- MacBook M1 / Safari / other browsers: **NOT TESTED**.
- Video/trace: Playwright traces are kept on failure only.

| F7 drawing tools | drawings.spec (8) | toolbar present and keyboard-operable; horizontal line placed at the clicked price (pixel check); trendline/zone two clicks, Escape cancels; select+drag moves a line by the dragged distance while ordinary drags still pan; an active tool disables panning; delete/undo/redo/clear exact via buttons and keys; persistence across reload and timeframe switches; corrupted storage ignored; drawings never alter the backend decision overlays | VERIFIED PASS (2 mutations each break a test) |
