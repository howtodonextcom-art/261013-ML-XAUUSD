# IMPLEMENTATION STATE (checkpoint; read this first when resuming)

Updated: 2026-10-14. Rules: CLAUDE.md. Reference prompts: prompts/261014-12-24 (V4.2/V4.3) and V4.4 queue (P3-CLOSURE, P4, P5, LIVE INTEGRATION, P2, P6, P7, P8).

## Baseline
- HEAD `74d57b0` on main (pushed). Identity howtodonext.com. Gateway: `scripts/windows/run_gateway.ps1` -> http://127.0.0.1:8765.
- Tests at HEAD: 122 pytest passed; 30 Playwright (Chrome 155) passed at 7585a48, UI unchanged since.

## Completed and verified (evidence in docs/qa, docs/data, docs/research)
- Data layer: cursor, sessions, Parquet+SQLite store, crash recovery (live experiment EXACT), backfill ticks/M1/M5-H4, minute-level coverage, M1 parity 13258/13258 eligible (20.1% of bars), HTF aggregation parity exact.
- Dashboard + Chrome E2E (timeframes, chart interaction, connection failures, responsive).
- P3 package `services/intelligence/xau_intel`: indicators (MT5 definitions), zig-zag structure (BOS/CHoCH), regime, point-in-time snapshot; 50 tests; independent review round 2 fixed.

## In progress: P3-CLOSURE
1. MT5 indicator parity: script `mt5/scripts/DumpIndicators.mq5` compiled (copy in terminal MQL5\Scripts\xau_tmp_compile). **BLOCKED on one manual action**: run the script on an XAUUSD chart. Then `python benchmarks/mt5_indicator_parity.py`. Status NOT TESTED.
2. Pre-registered experiment for zig-zag k (docs/research/SWING_K_PREREGISTRATION.md) committed BEFORE running.
3. Zig-zag initialisation + intra-bar High/Low ordering policy; false breakout / liquidity sweep (causal, optional evidence).
4. CSV provenance checks (server/account_ref/terminal/symbol/timeframe/freshness + OHLC cross-check with the local store).

## Next executable actions (in order)
P3-CLOSURE items above -> regression -> independent re-review -> P4 (zones, pullback lifecycle, candle patterns, setup state machine, WAIT taxonomy) on offline certified data.

## Blockers
- MT5 chart action for the parity dump (manual). Mac M1: not available. Mode B (MQL5 bridge) not started.

## Known open items
M1 bar 2026-10-13 16:58 quarantined; DST untested (EU 2026-10-25, US 2026-11-01 are the first real chances); e2e flaky once (O1); gate F6 PARTIAL.

## Last test result
pytest 122 passed (HEAD 74d57b0).
