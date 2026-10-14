# RELEASE ACCEPTANCE (2026-10-14)

Status words: VERIFIED PASS, PARTIAL, FAILED, BLOCKED, NOT TESTED, NOT IMPLEMENTED. Master Prompt V4.2/V4.3 is **not complete**; this lists what each gate currently has.

| Gate | Status | Evidence / gap |
|---|---|---|
| A+ Data integrity | PARTIAL | restart/crash recovery, seam coverage, isolation, M1/HTF parity, quarantine all tested (see test counts below). Gaps: parity covers 20.1% of M1 bars, one unexplained bar, DST untested, crash experiment n=1 |
| B Mode B / A-B / end-to-end latency | NOT IMPLEMENTED | |
| C1 Indicators, causal structure | PARTIAL | EMA/RSI/MACD/ATR + features, causal zig-zag structure (BOS/CHoCH), regime, point-in-time snapshot: 44 tests (causality, no repaint, oracle equality). **MT5 indicator parity NOT TESTED** (script compiles, needs one manual run on a chart). False breakout / liquidity sweep implemented as candidates. Zig-zag k=2.5 chosen by an experiment pre-registered and pushed before it ran. Regime thresholds unvalidated. See docs/research/FEATURE_SPEC.md |
| C2 Setup lifecycle, decisions | PARTIAL | state machine + WAIT taxonomy + BUY/SELL/WAIT/BLOCKED with explanation, 47 setup tests (causal, mirrored, legal transitions, review round 4 fixed); running live in the gateway and displayed in the dashboard. Thresholds unvalidated; no outcome evidence |
| D1 Entry/Risk | PARTIAL | risk plan with MT5-real value per lot (tick_value inconsistency detected), lot rounding, margin, gates, shadow outcome simulator; execution_authorized always False. No paper ledger, daily-loss gate not evaluable, commission unknown (docs/research/RISK_GOVERNANCE.md) |
| D2 Replay/backtest | NOT IMPLEMENTED | |
| E1 ML shadow | NOT IMPLEMENTED | |
| E2 Dashboard | PARTIAL | live chart, 5 timeframes, honest states, decision panel (action, reason layers, setup, plan, next event) with ENTRY/SL/TP/zone overlays from the backend; no drawing tools/indicator toggles/replay/ML panels, no auth, Mac NOT TESTED |
| F1 Browser toolchain | VERIFIED PASS | Chrome 155 headed via Playwright 1.64 |
| F2 Functional coverage | PARTIAL | all 6 existing controls inventoried and tested; most requested controls do not exist |
| F3 Chart interaction | PARTIAL | pan/zoom/crosshair/timeframes verified; drawing tools and undo/redo NOT IMPLEMENTED |
| F4 Visual/responsive | PARTIAL | 11 viewport/zoom cases pass (zoom emulated); no pixel regression |
| F5 Data/strategy consistency | PARTIAL | no false-connected; stale/transport-stall verified; decision panel equals the backend record (11 tests, UI mutations caught); stale decision removed after 10 s; no account figures in the API. Backend/UI parity checked on the last received frame only |
| F6 Independent review | PARTIAL | one real review round; fixes not re-reviewed (RED_TEAM_FINDINGS.md) |
| Safety (no order path) | VERIFIED PASS (static) | scan of services/scripts/benchmarks/apps; the MQL5 scan covers the one existing script (DumpIndicators.mq5, read-only); no runtime guard |

Test totals at the time of this document: pytest 283 passed, 0 skipped; Playwright 44 passed.
Rollback: `git revert` the commit; `data/store` can be deleted and rebuilt with the backfill.
