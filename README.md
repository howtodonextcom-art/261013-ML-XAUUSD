# XAUUSD Trading Intelligence Terminal — vertical slice 1

Mode: `READ_ONLY + SHADOW + PAPER_SIMULATION`. No order is ever sent. No strategy signals exist yet.

## Run (Windows, PowerShell, MT5 already running and logged in)

```powershell
cd Z:\Coding\261013-ML-XAUUSD
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install MetaTrader5 numpy pandas fastapi "uvicorn[standard]" pytest httpx
.\scripts\windows\run_gateway.ps1 -TerminalPath "C:\Program Files\MetaTrader 5\terminal64.exe"
```

Open http://127.0.0.1:8765/ . Check `http://127.0.0.1:8765/api/health`.
Always pass `-TerminalPath`: more than one MT5 terminal may be installed.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit -q
.\.venv\Scripts\python.exe scripts\windows\probe_mt5.py          # connection + symbol probe
.\.venv\Scripts\python.exe benchmarks\candle_parity.py 240       # engine vs MT5 bars
```

## Status (honest)

Done and verified on real MetaQuotes-Demo data: Mode A tick ingestion, M1/M5/M15/H1/H4 candle engine,
WebSocket + live dashboard, health/staleness, candle parity (238/240 M1 bars exact), 11 unit tests.

Not done: Mode B EA bridge and A/B benchmark, strategy/rulebook engines, risk/entry, replay/backtest, ML,
persistence, auth/TLS, Next.js dashboard, historical backfill, Mac testing.
See `docs/architecture/` and `docs/qa/KNOWN_LIMITATIONS.md`.
