# IMPLEMENTATION STATE (checkpoint; read this first when resuming)

Updated: 2026-10-14 (Master Prompt Level 5.1). Rules: CLAUDE.md. Product contract: docs/product (reconstructed; acceptance matrix is the status source). Check `git log` / `git status` first. Gateway: `scripts/windows/run_gateway.ps1` (prints the dashboard URL with the one-time token) -> http://127.0.0.1:8765 (authentication ON).

## Baseline at the start of Level 5.1 (reported, then re-verified)
6cfd8ba: 347 pytest, 59 Playwright, P6 INSUFFICIENT_EVIDENCE, P7 NO_EVIDENCE_OF_PREDICTIVE_SKILL, holdout unused.

## Done in Level 5.1 (evidence in the cited files)
- **Mode B audit and fixes:** EA v1.1 (paginated CopyTicks, `want = page + g_last_cnt` after the Python model of the algorithm lost ticks when more than a page shared one millisecond; account_ref in the file name; `#gap` markers); reader gap/restart detection; `ab_capture.py` identity gate (mismatch, missing header, unpinned account, unverified Mode A, symbol difference => exit 4, no result file). docs/architecture/MODE_B.md, docs/qa/MT5_LIVE_VERIFICATION.md, scripts/windows/verify_live_session.ps1.
- **Security:** token authentication (HttpOnly SameSite=Strict cookie + bearer + WebSocket handshake), rate limit, bind guard, Host/Origin with optional private hosts only while authenticated; threat model docs/architecture/THREAT_MODEL.md; token file git-ignored.
- **Privacy:** lot hidden by default (privacy mode); public decision byte-identical across affordable accounts over a 60-step price path (tests); reveal only by start-up env; reveal mode leaks equity to <1% (tested, mutation check).
- **Latency/reliability:** heavy recompute moved to a worker process (benchmarks/gil_contention.py: scheduling-delay p99 19.6 ms in-process -> 0.11 ms process); end-to-end instrumentation (`pub_wall_ms`, `window.__lat`) and `benchmarks/e2e_latency.mjs` in real Chrome (results/p3); intel seq starts at wall-clock ms; DST mixed-window fix in OffsetEstimator (it could report a confident wrong 2.5 h offset); synthetic DST tests.
- **UI/QA:** visual regression baselines (5, decision card); interactive Chrome DevTools MCP QA: unauthenticated 401, token login, gateway stop -> DISCONNECTED/STALE with nothing actionable, restart -> reconnect with a new seq, no duplicate bars; emulated viewports/zoom (docs/qa/MCP_BROWSER_QA.md).
- **Docs synchronised:** README, KNOWN_LIMITATIONS, RELEASE_ACCEPTANCE, PRODUCT_ACCEPTANCE_MATRIX, RED_TEAM_FINDINGS.
- **Research integrity:** nothing in BACKTEST_PREREGISTRATION / CLARIFICATIONS / AMENDMENTS / ML_SHADOW_PREREGISTRATION was edited; no holdout bar was loaded by P6 or P7 code paths (`cut_bars` at the frozen `val_end`); no candidate or threshold was tuned.

## Status words (gates)
LIVE_AB_NOT_TESTED. Indicator parity NOT TESTED. Native browser zoom NOT TESTED (emulated only). Mac NOT TESTED. Real DST NOT TESTED. Live BUY/SELL NOT OBSERVED. F6 independent review: PARTIAL (see RED_TEAM_FINDINGS.md for the last pass and what was fixed after it).

## Next executable actions
1. **You (manual, about 40 min):** follow docs/qa/MT5_LIVE_VERIFICATION.md (attach `XauTickLoggerModeB`, run `DumpIndicators`), then `scripts\windows\verify_live_session.ps1`. Record the real outcome; choose Mode A / B / hybrid by the stated decision rule.
2. On 2026-10-25 (EU) and 2026-11-01 (US) check the server-offset logic live (`/api/health` detail) and the candle buckets across the switch.
3. Native browser zoom 100/125/150/200% by hand (or with a tool that drives the browser UI), and a Mac session over an SSH tunnel.
4. Research V2 only as a NEW pre-registered study on new future data (the P6/P7 holdout is not reusable as unseen); see docs/research.
5. Optional: Mode B as a gateway source only if the A/B decision rule is met and a second independent review passes.

## Known open items
M1 bar 2026-10-13 16:58 quarantined; thresholds unvalidated; approximate expiry times; no TLS; drawing tools are client-side only. Full list: docs/qa/KNOWN_LIMITATIONS.md.
