# IMPLEMENTATION STATE (checkpoint; read this first when resuming)

Updated: 2026-10-14 (Master Prompt Level 5 in progress). Rules: CLAUDE.md. Product contract: docs/product (reconstructed). Check `git log` / `git status` first. Gateway: `scripts/windows/run_gateway.ps1` -> http://127.0.0.1:8765.

## Baseline (re-verified this session)
- pytest 283 passed at HEAD 0f9db4c before the P6 work; Playwright 44 passed (last full run before the P6 work). P6 adds tests/unit/test_backtest.py (19) and test_backtest_real.py (4).

## Completed and verified
- Data layer, backfill (fixed 30-day grid), M1 hole detection, parity, crash recovery (docs/data, docs/qa).
- P3 indicators/structure/regime, P4 setup lifecycle (setup-1), P5 risk-1/gate-1/decide + shadow-1, live integration with the backend as the only decision source, public-plan privacy, stale handling (docs/qa/RED_TEAM_FINDINGS.md rounds 1-5).
- P6 replay/backtest engine (services/intelligence/xau_intel/backtest, benchmarks/p6_backtest.py): protocol frozen BEFORE code (BACKTEST_PREREGISTRATION.md, BACKTEST_IMPLEMENTATION_CLARIFICATIONS.md); simulator hand-calculated tests; prefix-invariance incl. a mutation check; determinism; independent plain-loop re-simulation of all 29 C4 trades (benchmarks/p6_resim_check.py, 0 mismatches). Dev+validation run done: **INSUFFICIENT_EVIDENCE** (7 validation trades < 20); the holdout is SEALED AND UNOPENED (never loaded; no marker file). Report: docs/research/BACKTEST_REPORT_DEVVAL.md.

## In flight (superseded by the checkpoint at the end of this file)
- Independent reviews (subagents): P6 engine and the round-5 fix re-review. Findings to be recorded in RED_TEAM_FINDINGS.md (round 6) and fixed with regression tests.
- Browser QA: the Playwright MCP is configured with browser chrome-for-testing which is NOT installed (error from the tool); real Google Chrome is driven through the chrome-devtools MCP instead (isolated profile). Interactive session confirmed live page, timeframe clicks, no console errors. Full scenario QA (10 scenarios, 3 viewports, zoom) not yet done.

## Next executable actions
1. Record review results; fix findings; rerun pytest + Playwright.
2. UI upgrade (decision panel): next required confirmation for WAIT, invalidation/expiry, distinct BLOCKED plan labelled NOT ELIGIBLE, evidence list; fixtures for the 10 scenarios; interactive Chrome QA; viewports 1440x900/1152x720/390x844.
3. Re-run devval from a committed clean tree so results name a clean SHA (deterministic: fingerprints must be identical).
4. P2 Mode B + latency, P7 ML shadow (only with trustworthy replay data; the holdout must stay untouched), P8 drawing tools/auth/Mac.

## Known open items
- P3 MT5 indicator parity NOT TESTED (needs the manual DumpIndicators run on an XAUUSD chart, then `python benchmarks/mt5_indicator_parity.py`).
- M1 bar 2026-10-13 16:58 quarantined; DST untested (EU 2026-10-25, US 2026-11-01); Mode B not started; Mac not available; thresholds unvalidated; approximate equity inference via the published lot.


## CHECKPOINT 2026-10-14 (end of Master Prompt Level 5 session)
- Tests: 347 pytest passed; 59 Playwright passed (real Chrome 155); mutation checks recorded per area.
- P6 backtest: frozen protocol + clarifications + amendments; engine reviewed independently; dev/validation = INSUFFICIENT_EVIDENCE (7 validation trades); **holdout sealed, never opened, no marker file**; deterministic (identical C4 fingerprint from a clean commit); results/p6.
- Reviews: round 5 re-review and round 6/6b re-reviews (independent subagents) found real defects, all fixed with regression tests except the documented residual equity/free-margin oracles (RISK_GOVERNANCE, KNOWN_LIMITATIONS). The round-6b fixes themselves were reviewed once more only by their own tests (no third independent pass): gate F6 stays PARTIAL.
- UI: decision card with the three reason layers, next required confirmation, expiry (approximate), recent setup events, NOT ELIGIBLE rendering of BLOCKED levels, STALE handling, seq guard; drawing tools; narrow-screen layout. Interactive MCP QA through Chrome DevTools MCP (the Playwright MCP browser is not installed): docs/qa/MCP_BROWSER_QA.md. Native browser zoom NOT TESTED.
- P2 Mode B: EA compiled (0 errors), reader and EA-algorithm model tested; A/B benchmark NOT TESTED until the EA is attached to a chart (manual); gateway has no Mode B source.
- P7 ML shadow: pre-registered, pipeline + tests, dev/validation NO_EVIDENCE_OF_PREDICTIVE_SKILL; holdout not loaded.
- Security posture: loopback only + Host/Origin allow-list (cross-site WebSocket read refused); still NO authentication (any local process can read the API); equity/free-margin inferable to about 0.2% by a patient observer (documented).

## Next executable actions
1. Manual (user): attach `XauTickLoggerModeB` to an XAUUSD chart, then `python benchmarks/ab_capture.py --minutes 30`; run `DumpIndicators` on a chart then `python benchmarks/mt5_indicator_parity.py`; optionally install the Playwright MCP browser (`npx @playwright/mcp install-browser chrome-for-testing`).
2. P6 follow-up only if more history becomes available: re-pre-register with a longer span; the current holdout stays sealed (open it once, together with P7, only if the validation gate ever passes).
3. Authentication for the API (token per run, required for any non-loopback binding) before any remote access; Mac M1 compatibility run (no Mac available here); DST window (EU 2026-10-25, US 2026-11-01) re-check of the server-offset logic.
4. A third independent review of the round-6b changes and of the drawing tools / P7 code.
