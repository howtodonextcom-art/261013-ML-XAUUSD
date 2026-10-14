# RELEASE ACCEPTANCE (2026-10-14, Level 5.1)

Status words: VERIFIED PASS, PARTIAL, FAILED, BLOCKED, NOT TESTED, NOT IMPLEMENTED. "Verified" is a statement about software behaviour, never about profitability. The product is a decision-support terminal with **no demonstrated trading edge**.

| Gate | Status | Evidence / gap |
|---|---|---|
| A Data integrity | PARTIAL | restart/crash recovery, seam coverage, isolation, M1/HTF parity, quarantine, fixed chunk grid, M1-hole detection tested. Gaps: parity covers about 20% of M1 bars, one unexplained quarantined bar, crash experiment n=1, real DST NOT TESTED (synthetic DST tested) |
| B1 Mode B (EA + reader) | PARTIAL | EA v1.1 compiled; reader and an EA-algorithm model tested (found/fixed a same-millisecond pagination stall); read-only enforced for every .mq5 |
| B2 A/B capture benchmark | LIVE_AB_NOT_TESTED | needs the EA attached manually; identity gate tested (mismatch = FAILED exit 4); docs/qa/MT5_LIVE_VERIFICATION.md |
| B3 End-to-end latency | PARTIAL | measured in real Chrome: gateway p99 about 6.8 ms, delivery p99 about 7 ms, render p99 about 17 ms (foreground); background tab renders about 1 s late by design; GIL contention measured (in-process heavy work p99 19.6 ms, worker process 0.11 ms) and the worker layout adopted. Broker-to-PC leg not measurable (0.3 s clock difference); live series across many bar closes not collected |
| C1 Indicators, structure | PARTIAL | 44+ tests (causality, no repaint). **MT5 indicator parity NOT TESTED** (manual run). Thresholds unvalidated |
| C2 Setup lifecycle, decisions | PARTIAL | state machine, WAIT taxonomy, mirrored SELL (incl. wording), invalidated/missed/expired shown; live ENTRY_ELIGIBLE not observed |
| D1 Risk/entry | PARTIAL | risk-1 with MT5-real value per lot; privacy mode hides the lot; paper simulator with ask-side SELL stops; no paper ledger, daily-loss gate not evaluable, commission unknown |
| D2 Replay/backtest | VERIFIED PASS (software) / INSUFFICIENT_EVIDENCE (research) | engine: prefix invariance with mutation check, determinism, hand-calculated simulator, independent re-simulation, independent review (BACKTEST_AMENDMENTS.md); result INSUFFICIENT_EVIDENCE; holdout sealed and unopened |
| E1 ML shadow | VERIFIED PASS (software) / NO_EVIDENCE_OF_PREDICTIVE_SKILL (research) | pre-registered, leakage tests mutation-checked; not in the UI, never feeds a decision |
| E2 Dashboard | PARTIAL | everything listed in README works in real Chrome (fixtures and live); BUY/SELL on live data not observed; Mac NOT TESTED |
| F1 Browser toolchain | VERIFIED PASS | Chrome 155 via Playwright suite; Chrome DevTools MCP for interactive QA; Playwright MCP's browser is not installed (not used) |
| F2 Functional coverage | VERIFIED PASS | every control inventoried (inventory test fails on an unknown control); drawing tools tested with real mouse events and pixel checks |
| F3 Chart interaction | PARTIAL | pan/zoom/crosshair/timeframes/drawing verified; native browser zoom NOT TESTED (emulated 100/125/150/200% only) |
| F4 Visual/responsive | PARTIAL | 1440x900, 1152x720, 390x844 pass; emulated zoom noted; visual regression of the decision card on deterministic fixtures (5 baselines, Windows/Chrome only) |
| F5 Data/strategy consistency | VERIFIED PASS (fixtures) / PARTIAL (live) | UI equals the backend record; stale/disconnect removes every actionable element; reconnect after a gateway restart verified by hand (MCP) and by test |
| F6 Independent review | PARTIAL | independent reviewers found real defects in rounds 5, 6, 6b, 7 and 8 (no Critical/High in round 8); the round-8 fixes are covered by their own tests with mutation checks but have no further independent pass (RED_TEAM_FINDINGS.md) |
| G Security | PARTIAL | token auth + cookie + WebSocket handshake + Host/Origin + rate limit + bind guard tested (mutation-checked); privacy mode tested by inference sweeps; no TLS, no per-user accounts; plain HTTP off-loopback only through a tunnel/VPN (not tested on a Mac) |
| Safety (no order path) | VERIFIED PASS (static) | scan of services/scripts/benchmarks/apps and every MQL5 source; no runtime guard |

Test totals are in docs/qa/IMPLEMENTATION_STATE.md (checkpoint).
Rollback: `git revert` the commit; `data/store` can be deleted and rebuilt with the backfill; delete `configs/api_token` to rotate the token.
