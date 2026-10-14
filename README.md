# XAUUSD Trading Intelligence Terminal

Mode: `READ_ONLY + SHADOW + PAPER_SIMULATION`. No order is ever sent, modified or cancelled: there is no order code path in Python or MQL5 (enforced by `tests/unit/test_safety.py` and a test over every `.mq5`). BUY/SELL/WAIT/BLOCKED are **research decisions** for a hypothetical paper plan; `execution_authorized` is a constant `False`.

**Do not confuse functioning software with a profitable strategy.** The strategy has no demonstrated edge: the pre-registered backtest is INSUFFICIENT_EVIDENCE and the ML shadow model shows no predictive skill (see below).

## What exists (evidence in `docs/`)
- **Data:** live XAUUSD ticks from a pinned MetaTrader 5 terminal (Mode A, MetaTrader5 Python package, terminal-identity isolation), crash-safe capture to Parquet + SQLite manifest, restart recovery, idempotent backfill (ticks, M1, M5, M15, H1, H4), candle engine equal to MT5 bars on settled history (13 258/13 258 eligible M1 bars exact; 1 bar quarantined), real MT5 M1 history holes detected and reported (never filled).
- **Intelligence** (`services/intelligence`): EMA/RSI/ATR/MACD per MT5 definitions (MT5 parity **NOT TESTED**: needs one manual run in the terminal), causal zig-zag structure, BOS/CHoCH, liquidity sweeps, regime, setup lifecycle (`setup-1`: forming, pullback, zone, confirmation, entry window, eligible, invalidated / missed / expired), risk plan (`risk-1`), gates (`gate-1`), decision (`cand-1`), paper outcome simulator.
- **Dashboard** (static page + Lightweight Charts): live M1-H4 chart, honest connection states, BUY/SELL/WAIT/BLOCKED with Market/Strategy/Gate reasons, next required confirmation, hypothetical Entry/SL/TP/R:R, invalidation and approximate expiry, recent setup events, BLOCKED levels drawn as NOT ELIGIBLE, STALE handling, drawing tools (horizontal line, trendline, zone; select/drag/delete/undo/redo; localStorage). The backend is the only decision source.
- **Security:** loopback-only binding, token authentication (HttpOnly SameSite cookie + bearer, authenticated WebSocket handshake, rate limit), Host/Origin allow-list, **privacy mode: the lot is hidden by default** (`docs/architecture/THREAT_MODEL.md`).
- **Research:** deterministic replay/backtest (P6, `docs/research/BACKTEST_*`), ML shadow (P7, `docs/research/ML_SHADOW_*`), both pre-registered before any run, holdout sealed and never opened.
- **Mode B (P2):** read-only MQL5 file-logging EA + reader + A/B benchmark: built and tested offline, **LIVE_AB_NOT_TESTED** (`docs/qa/MT5_LIVE_VERIFICATION.md`).
- **Latency (measured, this machine):** gateway receipt-to-publish p50 about 1.1 ms, p99 about 6.8 ms (live, n=2033); heavy analysis runs in a worker process because in the same process it delayed the tick path to p99 19.6 ms (`benchmarks/gil_contention.py`); browser delivery p99 about 7 ms and render p99 about 17 ms in foreground real Chrome (`benchmarks/e2e_latency.mjs`, `results/p3/`). Market (broker-to-PC) latency is not measurable: the broker clock and this PC differ by about 0.3 s.
- **Tests:** 506 pytest and 117 Playwright tests in real Chrome (incl. visual regression); interactive Chrome DevTools MCP QA in `docs/qa/MCP_BROWSER_QA.md`.

## Research status
| Study | Result |
|---|---|
| P6 backtest (cand-1 vs controls) | **INSUFFICIENT_EVIDENCE** (7 validation trades, minimum 20); holdout sealed |
| P7 ML shadow | **NO_EVIDENCE_OF_PREDICTIVE_SKILL** (validation AUC 0.499) |
| Indicator parity with MT5 | **NOT TESTED** (manual step) |
| Mode A vs Mode B | **LIVE_AB_NOT_TESTED** (manual step) |

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
# 3) run the gateway + dashboard (loopback only, authentication on)
.\scripts\windows\run_gateway.ps1          # prints the dashboard URL with the one-time token
.\scripts\windows\open_dashboard.ps1       # opens it later from configs\api_token
```
Open the printed URL once: the browser keeps an HttpOnly session cookie and the token disappears from the address bar. `configs/source.json`, `configs/api_token`, `data/store`, `.env` are git-ignored and must stay private (the repository is public). To rotate the token, delete `configs/api_token` and restart.

Privacy mode is the default: the plan shows levels and R:R but no lot. `XAU_REVEAL_SIZE=1` (start-up environment variable) publishes the lot; read the threat model first.

## Verify
```powershell
.\.venv\Scripts\python.exe -m pytest tests -q                       # unit + integration (check -rs for skips)
npm install                                                           # once
npx playwright test                                                   # real Chrome; the gateway must be running (the suite logs in with configs\api_token)
.\.venv\Scripts\python.exe scripts\windows\data_qa.py --out data\qa_latest.json
.\scripts\windows\verify_live_session.ps1                             # MT5 A/B + indicator parity once the manual MT5 steps are done
.\.venv\Scripts\python.exe benchmarks\gil_contention.py               # GIL contention
node benchmarks\e2e_latency.mjs                                       # browser latency in real Chrome
```

## macOS (MacBook M1)
The Python MetaTrader5 package has no macOS ARM build, so MT5 access stays on Windows. A Mac can only be a browser client (and research workstation). Recommended: an SSH tunnel to the loopback binding, or a private VPN address passed with `-AllowedHosts` (authentication must stay on; plain HTTP is not for untrusted networks). **NOT TESTED on a Mac.**

## Docs
`docs/handover/` (USER_GUIDE, WINDOWS_RUNBOOK, MAC_ACCESS_GUIDE, MT5_VERIFICATION_REPORT, CHROME_QA_REPORT, RESEARCH_STATUS, SECURITY_AND_ROLLBACK), `docs/product/` (requirements, acceptance matrix), `docs/qa/` (IMPLEMENTATION_STATE = checkpoint, RELEASE_ACCEPTANCE, KNOWN_LIMITATIONS, RED_TEAM_FINDINGS, BUG_FIX_LOG, BROWSER_TEST_MATRIX, MCP_BROWSER_QA, MT5_LIVE_VERIFICATION, data reports), `docs/research/`, `docs/architecture/` (THREAT_MODEL, MODE_B), `docs/data/`. Project rules (Git identity, push policy, safety): `CLAUDE.md`.
