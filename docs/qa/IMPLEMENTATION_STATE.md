# IMPLEMENTATION STATE (checkpoint; read this first when resuming)

Updated: 2026-10-14. Rules: CLAUDE.md. Prompts: prompts/261014-12-24 (V4.2/V4.3) and the V4.4 queue (P3-CLOSURE, P4, P5, LIVE INTEGRATION, P2, P6, P7, P8).

## Baseline
- Check `git log` / `git status` first. Gateway: `scripts/windows/run_gateway.ps1` -> http://127.0.0.1:8765. Tests: 237 pytest passed; 30 Playwright (Chrome 155) passed at 7585a48, UI unchanged since.

## Completed and verified (evidence: docs/qa, docs/data, docs/research)
- Data layer, crash recovery, backfill, coverage, M1/HTF parity, dashboard + Chrome E2E.
- P3 `services/intelligence/xau_intel`: indicators (MT5 definitions), zig-zag structure k=2.5 (pre-registered experiment, commit-ordered), BOS/CHoCH, liquidity sweeps / false breakouts, regime, point-in-time snapshot, MT5-dump provenance (fail closed). Independent review rounds 2, 3, 4 fixed (RED_TEAM_FINDINGS.md).
- P4 `xau_intel/setups`: quantified candle patterns, zones from confirmed swings, direction context + alignment, setup lifecycle state machine (`setup-1`), WAIT taxonomy. Spec: docs/research/SETUP_LIFECYCLE.md.
- P5 (partial) `xau_intel/decision`: risk plan with MT5-real value per lot (tick_value inconsistency detected: 0.1 vs 100 USD per 1.00), research decision BUY/SELL/WAIT/BLOCKED with market/strategy/gate layers; `execution_authorized` always False.

## P3-CLOSURE
- **BLOCKED on one manual action**: run `DumpIndicators` on an XAUUSD chart (Navigator > Scripts > xau_tmp_compile; script recompiled 0 errors). Then `python benchmarks/mt5_indicator_parity.py` (0 PASS, 1 FAIL, 3 not tested, 4 provenance rejected). Status NOT TESTED. Gate P3 = PARTIAL.

## Next executable actions (in order)
1. P5 remainder: shadow outcome simulator (fill/no-fill, TP first / SL first / timeout / inconclusive, net P/L), spec snapshot stored in the store, docs (RISK_GOVERNANCE).
2. LIVE INTEGRATION: run the intelligence engine from the gateway data (closed bars from the store + live), expose via API, show setup/decision in the dashboard (backend is the only decision source), Chrome QA.
3. P6 deterministic replay + backtest (C0-C7), P2 Mode B + latency, P7 ML shadow, P8 drawing tools / Mac.

## Known open items
M1 bar 2026-10-13 16:58 quarantined; DST untested (EU 2026-10-25, US 2026-11-01); e2e flaky once (O1); gate F6 PARTIAL (round fixes not re-reviewed); thresholds of regime/setup/risk/gate are unvalidated design parameters; Mode B not started; Mac not available.
