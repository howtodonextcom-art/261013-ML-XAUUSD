# Chrome QA report (2026-10-14, Level 5.2)

Status words: VERIFIED PASS, PARTIAL, NOT TESTED. Anything driven by viewport/DPR or CSS-zoom emulation is labelled **EMULATED**; it is never reported as native.

## Automated regression (Playwright, real Chrome, global-setup token cookie)
88 tests. First full run: 85 passed, 2 failed (`chart.spec` drag-to-pan, `connection.spec` gateway stop/restart), 1 not run. Both passed when re-run alone (9/9) and in a second full run (88/88): **PARTIAL for stability** (two timing-sensitive tests flaked once under full-suite load; cause not isolated). Backend: 433 pytest passed.

## Interactive session, Chrome DevTools MCP (isolated browser context, live gateway after the round-9 fixes)
| Check | Result |
|---|---|
| Token login (`/?token=`) then clean URL, no token in the address bar | VERIFIED PASS |
| Live decision WAIT/AWAITING_PULLBACK, UI equals `/api/intel` (action, reason) | VERIFIED PASS |
| Five regions present: live market (header), market intelligence, M1 shadow (separate heading, "NOT a decision"), decision and risk, history and research | VERIFIED PASS |
| V2 shadow section arrives from the asynchronous job (kind SHADOW_OBSERVATION, execution_authorized false) | VERIFIED PASS |
| Layer buttons (EMA20, Structure) toggle `aria-pressed` and persist in `xau.layers.v1` | VERIFIED PASS |
| Gateway stopped with layers on: DISCONNECTED + STALE, decision STALE, no plan, shadow empty, live-region announcement | VERIFIED PASS |
| Gateway restarted: reconnects to CONNECTED_ACTIVE and WAIT, layer choice kept | VERIFIED PASS |
| Console errors/warnings during the session | none |
| Viewport 390x844 (mobile DPR 3), 1152x720, 1440x900: no horizontal overflow at 390 | EMULATED, PASS |
| Browser zoom 100/125/150/200%: CSS zoom, no horizontal overflow | EMULATED, PASS; native browser zoom **NOT TESTED** |
| Drawings create/drag/delete/undo/redo | Playwright suite PASS; MCP drawing session was done in Level 5.1 (docs/qa/MCP_BROWSER_QA.md), not repeated now |
| BUY/SELL/BLOCKED display | fixtures only (Playwright, visual baselines); live BUY/SELL **NOT OBSERVED** |

## Accessibility
Verified: landmarks (banner, main, two named complementary regions), headings, polite live regions for decision and data state, focus-visible, DOM order equal to reading order and narrow visual order, keyboard order (Playwright `a11y.spec`). Not covered: screen-reader testing, contrast audit by tool, native zoom/reflow. PARTIAL.

## Evidence
Screenshots: `qa-artifacts/mcp_live_1440.png`, `qa-artifacts/mcp_live_390.png` (market data only; no account data; `qa-artifacts/` is not pushed unless requested).

## Level 5.4 additions (2026-10-14)
- MCP, fixtures S1 (no direction), S4 BUY, S5 SELL, S6 BLOCKED, S7 INVALIDATED/MISSED injected through the page's own websocket handler (tests/e2e/mcp_fixture_injector.js): action, primary reason, plain-words line, next required, plan and event list rendered as expected; BLOCKED never shows BUY/SELL in its explanation. Fixture PASS proves rendering only, not live signals.
- MCP live: timeframe M15 click -> 2000 bars; Tab moves a visible 2 px focus ring; UI action equals `/api/intel`; a real live V2 trigger (M1 rejection) appeared with "no plan: SL_TOO_CLOSE" (broker stops level), the shadow panel kept it apart from the V1 decision.
- Playwright: 89 tests; repeated full-suite runs under CPU load are recorded in IMPLEMENTATION_STATE.md.
- Screenshots: qa-artifacts/mcp_fixture_S6_blocked_1440.png, mcp_live_1440_v53.png (market data only; not pushed).

## Manual checklist for native browser zoom (about 5 minutes, NOT TESTED until you do it)
In real Chrome, open the dashboard, then for each of 100%, 125%, 150%, 200% (Ctrl + plus / Ctrl+0): (1) no horizontal scrollbar; (2) the decision card text is not cut off; (3) the chart still pans/zooms with the mouse; (4) draw an H-line, reload, it is still at the same price; (5) the toolbar buttons stay reachable (wrap, not hidden). Note PASS/FAIL per zoom level here and in PRODUCT_ACCEPTANCE_MATRIX.md (R-N4).
