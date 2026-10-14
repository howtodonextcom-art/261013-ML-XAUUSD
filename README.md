# XAUUSD Trading Intelligence Terminal

Mode: `READ_ONLY + SHADOW + PAPER_SIMULATION`. No order is ever sent; there is no order code path (enforced by `tests/unit/test_safety.py`). There are **no strategy signals yet** (no BUY/SELL/WAIT engine): this release is the verified data foundation plus a live chart.

## What exists (verified, with evidence in `docs/`)
- Live XAUUSD ticks from a pinned MetaTrader 5 terminal (Mode A, MetaTrader5 Python package) with terminal-identity isolation.
- Crash-safe capture to Parquet + SQLite manifest, restart recovery from persisted data, idempotent historical backfill (ticks, M1, M5, M15, H1, H4).
- Tick-driven candle engine (Bid basis, MT5-compatible tick_volume), M1 candles rebuilt from settled MT5 historical ticks equal MT5 bars: 13 258/13 258 eligible bars exact (20.1% of stored M1 bars; 1 bar quarantined). The live path is verified separately on two short captures only (417 s and 181 s), not by this figure.
- M1 -> M5/M15/H1/H4 aggregation equal to MT5's native bars (0 mismatches).
- Dashboard (Lightweight Charts) with real history on all timeframes, honest connection states (`CONNECTED_ACTIVE`, `CONNECTED_IDLE`, `STALE`, `TRANSPORT_STALLED`, `DISCONNECTED`, `SOURCE_MISMATCH`, ...), stale prices struck through.
- Tests: 151 pytest passed (3 tests use the real terminal, 4 the local data store) + 30 Playwright tests in real Chrome.

- Offline multi-timeframe intelligence (`services/intelligence`): MT5-definition EMA/RSI/ATR/MACD and derived features, causal ATR zig-zag market structure (HH/HL/LH/LL, BOS/CHoCH), regime classification, point-in-time snapshots. Context only: it outputs no BUY/SELL. MT5 indicator parity is NOT yet tested (see `docs/research/FEATURE_SPEC.md`).

## Not built yet
MQL5 Mode B bridge and A/B benchmark, end-to-end latency, setup lifecycle/decisions/risk, replay and backtest, ML, drawing tools, authentication/TLS, Mac testing. See `docs/qa/KNOWN_LIMITATIONS.md` and `docs/qa/RELEASE_ACCEPTANCE.md`.

## Install and run (Windows 11, PowerShell, MT5 running and logged in)
```powershell
cd Z:\Coding\261013-ML-XAUUSD
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install MetaTrader5 numpy pandas pyarrow fastapi "uvicorn[standard]" pytest httpx
# 1) pin the terminal you want (several MT5 terminals may be installed; never rely on the default)
Copy-Item configs\source.example.json configs\source.json
.\.venv\Scripts\python.exe scripts\windows\pin_identity.py "C:\Program Files\MetaTrader 5\terminal64.exe"   # prints expected{} to paste
# 2) historical data (bounded; widen deliberately)
$env:PYTHONPATH="services\gateway"
.\.venv\Scripts\python.exe -m xau_gateway.backfill --hours 336 --bars-days 70 --htf
# 3) run the gateway + dashboard (loopback only)
.\scripts\windows\run_gateway.ps1
```
Open **http://127.0.0.1:8765/** (use the IP: `localhost` may add about 200 ms by trying IPv6 first). Health: `/api/health`.
`configs/source.json`, `data/store`, `.env` are git-ignored and must stay private (the repository is public).

## Verify
```powershell
.\.venv\Scripts\python.exe -m pytest tests -q                       # unit + integration (integration needs the terminal and skips otherwise: check -rs)
.\.venv\Scripts\python.exe scripts\windows\data_qa.py --out data\qa_latest.json   # manifest, quality, parity, coverage, warm-up
npm install                                                           # once
npx playwright test                                                   # real Chrome, gateway must be running
```
Other tools: `benchmarks/candle_parity.py`, `live_vs_history.py`, `history_settle_probe.py`, `range_window_probe.py`, `scripts/windows/crash_recovery_test.sh`, `dataset_manifest.py`.

## macOS (MacBook M1)
The Python MetaTrader5 package has no macOS ARM build, so MT5 access stays on Windows. A Mac is intended as a browser client (and research workstation) reaching the Windows gateway over a private network. The gateway binds 127.0.0.1 only and has **no authentication yet**: do not expose it. Mac access is **NOT TESTED**; see `docs/architecture/CONNECTIVITY_MATRIX.md`.

## Docs
`docs/data/` (HISTORICAL_DATA_SPEC, STORAGE_RECOVERY, SOURCE_IDENTITY, DATASET_MANIFEST), `docs/qa/` (RCA, DATA_QUALITY_REPORT, BACKFILL_REPORT, BUG_FIX_LOG, BROWSER_TEST_MATRIX, UI_CONTROL_INVENTORY, RED_TEAM_FINDINGS, AUTONOMOUS_QA_REPORT, RELEASE_ACCEPTANCE, KNOWN_LIMITATIONS), `docs/architecture/`.
Project rules (Git identity, push policy, safety): `CLAUDE.md`.
